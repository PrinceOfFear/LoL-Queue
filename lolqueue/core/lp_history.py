"""PDL por partida, com origem e precedência explícitas.

O histórico público de partidas não traz o delta de PDL. Já o cliente
local recebe, ao fim da ranqueada, uma notificação com ``gameId`` e
``leaguePointsDelta``. Este módulo guarda essa confirmação oficial e a
relaciona à linha do OP.GG pelo id numérico local, horário de término,
fila e campeão. Também aceita um delta informado manualmente, mas só
depois de validar a mesma associação, e deixa a origem visível — nunca
como uma estimativa enganosa.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

from ..config import lp_history_path
from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from ..lcu.credentials import client_install_dir
from ..lcu.events import LcuJsonApiEvents

if TYPE_CHECKING:
    from .summoner_history import MatchSummary


RANKED_QUEUES = {420: "SOLORANKED", 440: "FLEXRANKED"}
RANKED_QUEUE_IDS = {queue_type: queue_id for queue_id, queue_type in RANKED_QUEUES.items()}

# A origem segue junto do valor salvo para que a interface nunca chame de
# "oficial" algo que o jogador preencheu consultando uma fonte externa. A
# ordem também protege a confirmação da Riot: uma importação tardia jamais
# pode apagar um evento ou a comparação local já comprovada.
LP_SOURCE_RIOT_EVENT = "riot_event"
LP_SOURCE_LOCAL_SNAPSHOT = "local_snapshot"
LP_SOURCE_MANUAL = "manual"
LP_SOURCE_PRIORITY = {
    LP_SOURCE_MANUAL: 0,
    LP_SOURCE_LOCAL_SNAPSHOT: 1,
    LP_SOURCE_RIOT_EVENT: 2,
}
LP_GAME_END_REASONS = frozenset(
    {
        "LEAGUE_POINTS_UPDATE",
        "LEAGUE_PROMOTED",
        "LEAGUE_DEMOTED",
    }
)
TRACE_FILE_LIMIT = 16
MATCH_END_TOLERANCE = timedelta(minutes=2)
LP_POLL_INTERVAL = 1.0
LP_IDLE_POLL_INTERVAL = 5.0
LP_CAPTURE_WINDOW = 180.0
TRACE_IMPORT_INTERVAL = 5.0
SNAPSHOT_SETTLE_SECONDS = 6.0
SNAPSHOT_POLL_INTERVAL = 2.0
END_PHASES = frozenset({"WaitingForStats", "PreEndOfGame", "EndOfGame"})
# A seleção seguinte ainda pode acontecer antes de o cliente gravar a
# confirmação da partida anterior. Só parar quando a próxima partida de
# fato começou evita perder esse pequeno atraso do pós-jogo.
NEW_GAME_PHASES = frozenset({"GameStart", "InProgress", "Reconnect"})
SNAPSHOT_START_PHASES = frozenset({"GameStart", "InProgress", "Reconnect"})
LP_DELTA_MARKER = "leaguePointsDelta"
LCU_RANKED_QUEUE_IDS = {
    "RANKED_SOLO_5X5": 420,
    "RANKED_FLEX_SR": 440,
}


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _source_priority(source: str) -> int:
    """Ordem de confiança usada ao reconciliar duas fontes do mesmo jogo."""

    return LP_SOURCE_PRIORITY.get(source, LP_SOURCE_PRIORITY[LP_SOURCE_RIOT_EVENT])


@dataclass(frozen=True)
class LpChange:
    """A alteração de PDL que o cliente associou a um jogo específico."""

    game_id: int
    queue_id: int
    delta: int
    league_points: int | None = None
    tier: str = ""
    division: str = ""
    #: Como este valor entrou no aplicativo. Registros antigos assumem o
    #: evento da Riot para manter a compatibilidade com o arquivo anterior.
    source: str = LP_SOURCE_RIOT_EVENT

    @classmethod
    def from_notification(cls, raw) -> "LpChange | None":
        """Lê somente o envelope oficial de fim de partida da Riot."""

        if not isinstance(raw, dict):
            return None
        if (
            _text(raw.get("changeReason")) != "GAME_END"
            or _text(raw.get("notifyReason")) not in LP_GAME_END_REASONS
        ):
            return None
        return cls._from_values(raw, source=LP_SOURCE_RIOT_EVENT)

    @classmethod
    def from_storage(cls, raw) -> "LpChange | None":
        """Relê um registro que este módulo já confirmou antes."""

        if not isinstance(raw, dict):
            return None
        source = _text(raw.get("source")) or LP_SOURCE_RIOT_EVENT
        if source not in LP_SOURCE_PRIORITY:
            # Um arquivo antigo não tinha origem. Uma origem desconhecida
            # recebe a proteção máxima, em vez de abrir chance de a escrita
            # manual substituir uma confirmação existente.
            source = LP_SOURCE_RIOT_EVENT
        return cls._from_values(
            {
                "gameId": raw.get("game_id"),
                "queueId": raw.get("queue_id"),
                "leaguePointsDelta": raw.get("delta"),
                "leaguePoints": raw.get("league_points"),
                "tier": raw.get("tier"),
                "rank": raw.get("division"),
            },
            source=source,
        )

    @classmethod
    def _from_values(
        cls, raw: dict, *, source: str = LP_SOURCE_RIOT_EVENT
    ) -> "LpChange | None":
        game_id = _int(raw.get("gameId"))
        queue_id = _int(raw.get("queueId"))
        delta = _int(raw.get("leaguePointsDelta"))
        if game_id is None or queue_id not in RANKED_QUEUES or delta is None:
            return None
        return cls(
            game_id=game_id,
            queue_id=queue_id,
            delta=delta,
            league_points=_int(raw.get("leaguePoints")),
            tier=_text(raw.get("tier")),
            division=_text(raw.get("rank") or raw.get("division")),
            source=source,
        )


@dataclass(frozen=True)
class ManualLpInput:
    """Um PDL que o jogador conferiu e quer associar a uma partida local.

    ``game_id`` é sempre o identificador numérico da LCU, não o id opaco do
    OP.GG. Os outros campos deixam `import_manual` conferir, antes de salvar,
    que a linha ainda pertence à conta, fila, campeão e horário corretos.
    """

    game_id: int
    queue_id: int
    champion_id: int
    ended_at: datetime
    delta: int


@dataclass(frozen=True)
class LpImportResult:
    """Resultado sem dados pessoais de uma tentativa de importar PDL."""

    imported: tuple[LpChange, ...] = ()
    rejected: int = 0


def parse_lp_changes(payload) -> tuple[LpChange, ...]:
    """Lê tanto o recurso atual quanto o envelope de notificações da Riot."""

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        listed = payload.get("leagueNotifications")
        if isinstance(listed, list):
            rows = listed
        elif isinstance(payload.get("notification"), dict):
            rows = [payload["notification"]]
        else:
            rows = [payload]
    else:
        return ()
    return tuple(change for row in rows if (change := LpChange.from_notification(row)))


def _changes_from_trace_document(document) -> tuple[LpChange, ...]:
    """Extrai notificações do JSON completo gerado pelo League Client.

    O arquivo ``LeagueClient-tracing.json`` atual não é NDJSON: ele é um
    objeto grande com ``entries`` e cada evento guarda seu corpo em ``dds``
    como outra string JSON. A versão antiga lia uma linha por vez, o que
    fazia todos esses corpos oficiais de PDL serem ignorados.

    Percorrer dicionários e listas também tolera pequenas alterações no
    envelope do trace, sem interpretar campos que não tenham o marcador
    específico da notificação de PDL.
    """

    changes: list[LpChange] = []
    pending = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            raw = value.get("dds")
            if isinstance(raw, str) and LP_DELTA_MARKER in raw:
                try:
                    changes.extend(parse_lp_changes(json.loads(raw)))
                except ValueError:
                    # Um evento incompleto durante a escrita do trace não
                    # invalida os outros eventos do mesmo arquivo.
                    pass
            # A pilha é LIFO; inverter preserva a ordem cronológica que o
            # cliente escreveu em ``entries``.
            pending.extend(reversed(tuple(value.values())))
        elif isinstance(value, list):
            pending.extend(reversed(value))
    return tuple(changes)


def _changes_from_legacy_trace_lines(text: str) -> tuple[LpChange, ...]:
    """Compatibilidade com traces antigos em que cada evento era uma linha."""

    changes: list[LpChange] = []
    for line in text.splitlines():
        if LP_DELTA_MARKER not in line:
            continue
        try:
            event = json.loads(line)
            raw = event.get("dds") if isinstance(event, dict) else None
            payload = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            continue
        changes.extend(parse_lp_changes(payload))
    return tuple(changes)


def _changes_from_trace_text(text: str) -> tuple[LpChange, ...]:
    """Lê tanto o trace atual em documento único quanto o formato antigo."""

    if LP_DELTA_MARKER not in text:
        return ()
    try:
        return _changes_from_trace_document(json.loads(text))
    except ValueError:
        # Enquanto o cliente ainda está fechando o arquivo, o documento
        # pode estar momentaneamente incompleto. O fallback ainda recupera
        # traces de versões que escreviam um evento JSON por linha.
        return _changes_from_legacy_trace_lines(text)


@dataclass(frozen=True)
class _LocalMatch:
    game_id: int
    queue_id: int
    champion_id: int
    ended_at: datetime


@dataclass(frozen=True)
class _RankedLocalGame:
    """SÃ³ o vÃ­nculo que prova que uma partida nova entrou no histÃ³rico."""

    game_id: int
    queue_id: int


@dataclass(frozen=True)
class _RankedQueueState:
    """Retrato oficial de uma fila no instante da consulta local."""

    queue_id: int
    league_points: int
    tier: str
    division: str
    wins: int
    losses: int


@dataclass(frozen=True)
class _RankedSnapshot:
    """Estado antes da partida, suficiente para confirmar um delta depois.

    Este nÃ£o Ã© um palpite de MMR. O valor sÃ³ vira um ``LpChange`` se a
    mesma fila tiver exatamente uma partida local nova e o retrato oficial
    de vitÃ³rias/derrotas confirmar que ela foi contabilizada.
    """

    puuid: str
    queue_id: int
    league_points: int
    tier: str
    division: str
    wins: int
    losses: int
    game_ids: tuple[int, ...]

    @classmethod
    def from_storage(cls, raw) -> "_RankedSnapshot | None":
        if not isinstance(raw, dict):
            return None
        puuid = raw.get("puuid")
        queue_id = _int(raw.get("queue_id"))
        league_points = _int(raw.get("league_points"))
        wins = _int(raw.get("wins"))
        losses = _int(raw.get("losses"))
        game_ids = raw.get("game_ids")
        if (
            not isinstance(puuid, str)
            or not puuid
            or queue_id not in RANKED_QUEUES
            or league_points is None
            or wins is None
            or losses is None
            or not isinstance(game_ids, list)
        ):
            return None
        ids = tuple(game_id for value in game_ids if (game_id := _int(value)) is not None)
        if len(ids) != len(game_ids):
            return None
        tier = _text(raw.get("tier")).upper()
        division = _text(raw.get("division")).upper()
        if not tier:
            return None
        return cls(
            puuid=puuid,
            queue_id=queue_id,
            league_points=league_points,
            tier=tier,
            division=division,
            wins=wins,
            losses=losses,
            game_ids=ids,
        )

    def to_storage(self) -> dict:
        return {
            "puuid": self.puuid,
            "queue_id": self.queue_id,
            "league_points": self.league_points,
            "tier": self.tier,
            "division": self.division,
            "wins": self.wins,
            "losses": self.losses,
            "game_ids": list(self.game_ids),
        }


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    timestamp = _int(value)
    if timestamp is not None:
        # O LCU usa milissegundos de época para ``gameCreation``.
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc)
    return None


def _participant_for_current_player(game: dict, puuid: str):
    """Encontra a linha do invocador, sem supor que ele vem em primeiro."""

    participants = game.get("participants")
    if not isinstance(participants, list):
        return None
    identities = game.get("participantIdentities")
    if isinstance(identities, list):
        participant_id = None
        for identity in identities:
            if not isinstance(identity, dict):
                continue
            player = identity.get("player")
            if isinstance(player, dict) and player.get("puuid") == puuid:
                participant_id = _int(identity.get("participantId"))
                break
        if participant_id is None:
            # Quando o cliente trouxe identidades, preferimos não associar
            # uma partida ao campeão de outra pessoa por suposição.
            return None
        return next(
            (
                participant
                for participant in participants
                if isinstance(participant, dict)
                and _int(participant.get("participantId")) == participant_id
            ),
            None,
        )
    # Builds antigos da LCU não traziam as identidades neste recurso; o
    # endpoint filtrado pelo PUUID mantinha o jogador em primeiro nesses casos.
    return participants[0] if participants and isinstance(participants[0], dict) else None


def _local_matches(client, end_index: int = 20) -> tuple[_LocalMatch, ...]:
    """Lê os ids numéricos das partidas da conta aberta no cliente."""

    try:
        summoner = client.get(endpoints.CURRENT_SUMMONER)
        puuid = summoner.get("puuid") if isinstance(summoner, dict) else None
        if not isinstance(puuid, str) or not puuid:
            return ()
        raw = client.get(endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=end_index))
    except LcuError:
        return ()
    games_block = raw.get("games") if isinstance(raw, dict) else None
    games = games_block.get("games") if isinstance(games_block, dict) else None
    if not isinstance(games, list):
        return ()

    found: list[_LocalMatch] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = _int(game.get("gameId"))
        queue_id = _int(game.get("queueId"))
        duration = _int(game.get("gameDuration"))
        created_at = _parse_datetime(game.get("gameCreationDate"))
        if created_at is None:
            created_at = _parse_datetime(game.get("gameCreation"))
        participant = _participant_for_current_player(game, puuid)
        champion_id = participant.get("championId") if isinstance(participant, dict) else None
        if (
            game_id is None
            or queue_id not in RANKED_QUEUES
            or duration is None
            or created_at is None
            or _int(champion_id) is None
        ):
            continue
        found.append(
            _LocalMatch(
                game_id=game_id,
                queue_id=queue_id,
                champion_id=int(champion_id),
                ended_at=created_at + timedelta(seconds=duration),
            )
        )
    return tuple(found)


def _current_puuid(client) -> str | None:
    """LÃª a identidade que a LCU diz estar aberta agora."""

    try:
        summoner = client.get(endpoints.CURRENT_SUMMONER)
    except ClientClosed:
        raise
    except LcuError:
        return None
    puuid = summoner.get("puuid") if isinstance(summoner, dict) else None
    return puuid if isinstance(puuid, str) and puuid else None


def _recent_ranked_games(
    client, puuid: str, end_index: int = 20
) -> tuple[_RankedLocalGame, ...] | None:
    """Ids de todas as ranqueadas recentes, sem depender do campeÃ£o.

    A lista usada para enriquecer o OP.GG precisa tambÃ©m de participante,
    campeÃ£o e horÃ¡rio. Para provar a existÃªncia de uma nova partida, no
    entanto, exigir esses campos sÃ³ abriria uma brecha quando a LCU ainda
    estÃ¡ terminando de preencher a linha. Aqui o id e a fila bastam.
    """

    try:
        raw = client.get(endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=end_index))
    except ClientClosed:
        raise
    except LcuError:
        return None
    games_block = raw.get("games") if isinstance(raw, dict) else None
    games = games_block.get("games") if isinstance(games_block, dict) else None
    if not isinstance(games, list):
        return None
    found: list[_RankedLocalGame] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = _int(game.get("gameId"))
        queue_id = _int(game.get("queueId"))
        if game_id is None or queue_id not in RANKED_QUEUES:
            continue
        found.append(_RankedLocalGame(game_id=game_id, queue_id=queue_id))
    return tuple(found)


def _gameflow_queue_id(payload) -> int | None:
    """Descobre a fila do jogo atual nas variantes conhecidas da LCU."""

    game_data = payload.get("gameData") if isinstance(payload, dict) else None
    if not isinstance(game_data, dict):
        return None
    values = [game_data.get("queueId"), game_data.get("gameQueueConfigId")]
    queue = game_data.get("queue")
    if isinstance(queue, dict):
        values.extend((queue.get("id"), queue.get("queueId")))
    for value in values:
        if (queue_id := _int(value)) in RANKED_QUEUES:
            return queue_id
    return None


def _ranked_queue_state(payload, queue_id: int) -> _RankedQueueState | None:
    """Converte a fila pedida do retrato de ranked da LCU, estritamente."""

    queues = payload.get("queues") if isinstance(payload, dict) else None
    if not isinstance(queues, list):
        return None
    for row in queues:
        if not isinstance(row, dict):
            continue
        raw_type = row.get("queueType")
        typed_queue = (
            LCU_RANKED_QUEUE_IDS.get(raw_type.strip().upper())
            if isinstance(raw_type, str)
            else None
        )
        direct_queue = _int(row.get("queueId"))
        # Se a Riot incluiu os dois campos, eles precisam concordar. Um
        # campo malformado jamais pode fazer PDL de Flex ir parar na Solo.
        if typed_queue is not None and direct_queue is not None and typed_queue != direct_queue:
            continue
        row_queue = direct_queue if direct_queue in RANKED_QUEUES else typed_queue
        if row_queue != queue_id:
            continue
        league_points = _int(row.get("leaguePoints"))
        wins = _int(row.get("wins"))
        losses = _int(row.get("losses"))
        tier = _text(row.get("tier")).upper()
        division = _text(row.get("division") or row.get("rank")).upper()
        if (
            league_points is None
            or wins is None
            or losses is None
            or wins < 0
            or losses < 0
            or not tier
        ):
            return None
        return _RankedQueueState(
            queue_id=queue_id,
            league_points=league_points,
            tier=tier,
            division=division,
            wins=wins,
            losses=losses,
        )
    return None


class LpHistory:
    """Registro durável de PDL e ponte entre o cliente e o histórico."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or lp_history_path()
        self._lock = threading.Lock()
        self._changes, self._pending_snapshot = self._load()
        self._seen_traces: dict[Path, int] = {}

    def _load(self) -> tuple[dict[int, LpChange], _RankedSnapshot | None]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}, None
        rows = raw.get("changes") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            return {}, None
        found: dict[int, LpChange] = {}
        for row in rows:
            change = LpChange.from_storage(row)
            if change is not None:
                found[change.game_id] = change
        snapshot = _RankedSnapshot.from_storage(raw.get("pending_snapshot"))
        return found, snapshot

    def _save_locked(self) -> None:
        target = self._path
        temp = target.with_name(target.name + ".part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "changes": [asdict(change) for change in self._changes.values()],
                "pending_snapshot": (
                    self._pending_snapshot.to_storage()
                    if self._pending_snapshot is not None
                    else None
                ),
            }
            temp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            temp.replace(target)
        except OSError:
            # O dado segue na memória nesta execução; uma falha de disco não
            # pode derrubar a vigia do cliente no pós-jogo.
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def record_many(self, changes: Iterable[LpChange]) -> tuple[LpChange, ...]:
        """Inclui deltas novos, sem rebaixar a confiança de um já salvo."""

        received = tuple(changes)
        new: list[LpChange] = []
        with self._lock:
            dirty = False
            for change in received:
                previous = self._changes.get(change.game_id)
                if (
                    previous is not None
                    and _source_priority(previous.source) > _source_priority(change.source)
                ):
                    continue
                if previous == change:
                    continue
                self._changes[change.game_id] = change
                new.append(change)
                dirty = True
            if dirty:
                self._save_locked()
        return tuple(new)

    def import_manual(self, client, rows: Iterable[ManualLpInput]) -> LpImportResult:
        """Salva valores informados pelo jogador só após validar a partida.

        Não há aproximação por hora, fila ou campeão. Cada entrada só passa
        se o `game_id` ainda estiver no histórico local da conta conectada e
        todos os metadados da linha coincidirem. Um evento Riot ou um
        snapshot local já confirmado sempre vence a importação manual.
        """

        submitted = tuple(rows)
        # A tela lista a mesma janela recente de vinte partidas. Pedir a
        # janela conhecida da LCU evita depender de um limite maior que pode
        # variar entre versões do cliente.
        local = {game.game_id: game for game in _local_matches(client)}
        accepted: list[LpChange] = []
        rejected = 0
        seen: set[int] = set()
        for row in submitted:
            if (
                not isinstance(row, ManualLpInput)
                or _int(row.game_id) is None
                or _int(row.queue_id) is None
                or _int(row.champion_id) is None
                or isinstance(row.delta, bool)
                or not isinstance(row.delta, int)
                or row.game_id in seen
            ):
                rejected += 1
                continue
            seen.add(row.game_id)
            game = local.get(row.game_id)
            if (
                game is None
                or row.queue_id not in RANKED_QUEUES
                or game.queue_id != row.queue_id
                or game.champion_id != row.champion_id
                or not isinstance(row.ended_at, datetime)
            ):
                rejected += 1
                continue
            ended_at = row.ended_at
            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(tzinfo=timezone.utc)
            if abs(game.ended_at - ended_at) > MATCH_END_TOLERANCE:
                rejected += 1
                continue
            accepted.append(
                LpChange(
                    game_id=row.game_id,
                    queue_id=row.queue_id,
                    delta=row.delta,
                    source=LP_SOURCE_MANUAL,
                )
            )

        imported: list[LpChange] = []
        with self._lock:
            dirty = False
            for change in accepted:
                previous = self._changes.get(change.game_id)
                # O usuário pode corrigir algo que ele próprio informou,
                # mas não pode trocar a confirmação da Riot nem a captura
                # local exata de antes/depois.
                if previous is not None and previous.source != LP_SOURCE_MANUAL:
                    rejected += 1
                    continue
                if previous == change:
                    continue
                self._changes[change.game_id] = change
                imported.append(change)
                dirty = True
            if dirty:
                self._save_locked()
        return LpImportResult(imported=tuple(imported), rejected=rejected)

    def change_for(self, game_id: int) -> LpChange | None:
        """Devolve o delta confirmado para um jogo, se ele já foi capturado."""

        with self._lock:
            return self._changes.get(game_id)

    def pending_snapshot(self) -> _RankedSnapshot | None:
        """Devolve o retrato antes da partida, inclusive apÃ³s reiniciar."""

        with self._lock:
            return self._pending_snapshot

    def save_pending_snapshot(self, snapshot: _RankedSnapshot) -> bool:
        """Guarda o ponto de comparaÃ§Ã£o antes da ranqueada comeÃ§ar."""

        with self._lock:
            if self._pending_snapshot == snapshot:
                return False
            self._pending_snapshot = snapshot
            self._save_locked()
            return True

    def clear_pending_snapshot(self, snapshot: _RankedSnapshot | None = None) -> bool:
        """Remove apenas o retrato que acabou de ser resolvido.

        O argumento evita que uma vigia velha apague o retrato de uma
        partida nova que jÃ¡ tenha substituÃ­do o anterior.
        """

        with self._lock:
            if self._pending_snapshot is None:
                return False
            if snapshot is not None and self._pending_snapshot != snapshot:
                return False
            self._pending_snapshot = None
            self._save_locked()
            return True

    def import_trace_logs(self, directory: Path | None = None) -> tuple[LpChange, ...]:
        """Recupera notificações recentes já escritas pelo cliente.

        Isto permite preencher o histórico já existente logo após instalar
        o recurso, desde que o cliente ainda tenha os logs dessas partidas.
        Só os envelopes de PDL são lidos; dados de inventário, chat e
        qualquer outro conteúdo do trace são ignorados.
        """

        if directory is None:
            install = client_install_dir()
            directory = install / "Logs" / "LeagueClient Logs" if install else None
        if directory is None or not directory.is_dir():
            return ()
        try:
            files = sorted(
                directory.glob("*LeagueClient-tracing.json"),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )[:TRACE_FILE_LIMIT]
        except OSError:
            return ()

        changes: list[LpChange] = []
        for path in files:
            try:
                marker = path.stat().st_mtime_ns
            except OSError:
                continue
            with self._lock:
                if self._seen_traces.get(path) == marker:
                    continue
                self._seen_traces[path] = marker
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            changes.extend(_changes_from_trace_text(text))
        return self.record_many(changes)

    def enrich_matches(
        self,
        client,
        matches: Iterable["MatchSummary"],
        *,
        import_logs: bool = True,
    ):
        """Anexa cada delta confirmado à linha correspondente do OP.GG."""

        if import_logs:
            self.import_trace_logs()
        local = _local_matches(client)
        with self._lock:
            changes = dict(self._changes)
        enriched = []
        for match in matches:
            candidate = self._match_local_game(match, local)
            change = changes.get(candidate.game_id) if candidate is not None else None
            enriched.append(
                replace(
                    match,
                    lp_delta=change.delta if change is not None else None,
                    lp_after=change.league_points if change is not None else None,
                    lp_queue=RANKED_QUEUES.get(change.queue_id, "") if change else "",
                    lp_source=change.source if change is not None else "",
                    local_game_id=candidate.game_id if candidate is not None else None,
                )
            )
        return tuple(enriched)

    @staticmethod
    def _match_local_game(match, local: Iterable[_LocalMatch]) -> _LocalMatch | None:
        candidates = []
        played_at = match.played_at
        if played_at.tzinfo is None:
            played_at = played_at.replace(tzinfo=timezone.utc)
        for game in local:
            if RANKED_QUEUES.get(game.queue_id) != match.queue_type:
                continue
            if game.champion_id != match.champion_id:
                continue
            distance = abs(game.ended_at - played_at)
            if distance <= MATCH_END_TOLERANCE:
                candidates.append((distance, game))
        # Um vínculo é útil apenas se for único. Escolher o "mais perto"
        # esconderia uma ambiguidade e poderia colar o PDL da partida errada.
        return candidates[0][1] if len(candidates) == 1 else None


class LpChangeTracker:
    """Acompanha a notificação oficial de PDL durante o pós-jogo.

    O cliente pode expor a mudança da partida anterior por alguns segundos
    antes de atualizar a atual. Por isso a janela inteira é acompanhada; um
    aviso novo nunca encerra a captura prematuramente.
    """

    def __init__(
        self,
        client,
        history: LpHistory,
        on_change: Callable[[LpChange], None] | None = None,
        now: Callable[[], float] = time.monotonic,
        event_listener_factory=LcuJsonApiEvents,
    ) -> None:
        self._client = client
        self._history = history
        self._on_change = on_change or (lambda _change: None)
        self._now = now
        self._event_listener_factory = event_listener_factory
        self._event_listener = None
        self._deadline: float | None = None
        self._next_poll = 0.0
        self._next_trace_import = 0.0
        self._initial_trace_import_pending = True
        # Ã‰ persistido no LpHistory. Assim uma atualizaÃ§Ã£o/reinÃ­cio do
        # LoL Queue no meio da partida nÃ£o perde o retrato de antes.
        self._snapshot = history.pending_snapshot()
        self._phase = ""
        self._snapshot_capture_pending = False
        self._next_snapshot_capture = 0.0
        self._next_snapshot_poll = 0.0
        self._fallback_not_before: float | None = None

    def start_live_events(self) -> None:
        """Assina o aviso instant\u00e2neo de PDL enquanto o cliente est\u00e1 aberto.

        O polling HTTP e o trace seguem como redund\u00e2ncia. A assinatura evita
        perder a notifica\u00e7\u00e3o curta entre dois ciclos de polling ou antes de o
        arquivo de trace terminar de ser escrito.
        """

        if self._event_listener is not None:
            return
        credentials = getattr(self._client, "credentials", None)
        if credentials is None:
            return
        listener = self._event_listener_factory(credentials, self.handle_lcu_event)
        self._event_listener = listener
        listener.start()

    def stop(self) -> None:
        """Interrompe a assinatura antes de descartar esta conex\u00e3o LCU."""

        listener, self._event_listener = self._event_listener, None
        if listener is not None:
            listener.stop()

    def handle_phase(self, phase) -> None:
        value = getattr(phase, "value", str(phase))
        self._phase = value
        if value in END_PHASES and self._deadline is None:
            self._deadline = self._now() + LP_CAPTURE_WINDOW
            self._next_poll = 0.0
            self._next_trace_import = 0.0
            self._fallback_not_before = self._now() + SNAPSHOT_SETTLE_SECONDS
            self._next_snapshot_poll = self._fallback_not_before
            self._snapshot_capture_pending = False
        elif value in NEW_GAME_PHASES:
            # A nova partida já começou; dali em diante o aviso anterior
            # não é mais urgente e o próximo fim de jogo abre outra janela.
            self._deadline = None
            self._fallback_not_before = None
        if value in SNAPSHOT_START_PHASES:
            self._snapshot_capture_pending = True
            self._next_snapshot_capture = 0.0
            self._capture_snapshot_if_due()

    def capture_current_game(self) -> bool:
        """Save an exact before-state for the ranked game in progress."""

        self._snapshot_capture_pending = True
        self._next_snapshot_capture = 0.0
        return self._capture_snapshot_if_due(force=True)

    def _capture_snapshot_if_due(self, *, force: bool = False) -> bool:
        if not self._snapshot_capture_pending:
            return False
        now = self._now()
        if not force and now < self._next_snapshot_capture:
            return False
        self._next_snapshot_capture = now + SNAPSHOT_POLL_INTERVAL
        try:
            session = self._client.get(endpoints.GAMEFLOW_SESSION)
        except ClientClosed:
            raise
        except LcuError:
            return False
        queue_id = _gameflow_queue_id(session)
        if queue_id is None:
            # Durante alguns instantes de GameStart a LCU pode devolver a
            # sessÃ£o sem gameData. Mantemos a tentativa pendente para a
            # prÃ³xima leitura, em vez de perder a partida por essa corrida.
            return False
        puuid = _current_puuid(self._client)
        if puuid is None:
            return False
        try:
            ranked = self._client.get(endpoints.CURRENT_RANKED_STATS)
        except ClientClosed:
            raise
        except LcuError:
            return False
        state = _ranked_queue_state(ranked, queue_id)
        if state is None:
            self._snapshot_capture_pending = False
            return False
        games = _recent_ranked_games(self._client, puuid)
        if games is None:
            return False
        snapshot = _RankedSnapshot(
            puuid=puuid,
            queue_id=queue_id,
            league_points=state.league_points,
            tier=state.tier,
            division=state.division,
            wins=state.wins,
            losses=state.losses,
            game_ids=tuple(sorted({game.game_id for game in games})),
        )
        self._snapshot = snapshot
        self._history.save_pending_snapshot(snapshot)
        self._snapshot_capture_pending = False
        return True

    def _announce(self, received: Iterable[LpChange]) -> None:
        for change in received:
            self._on_change(change)

    def _record_payload(self, payload) -> None:
        self._announce(self._history.record_many(parse_lp_changes(payload)))

    def handle_lcu_event(self, event: dict[str, object]) -> None:
        """Recebe somente o payload do endpoint ef\u00eamero de PDL via WAMP."""

        if event.get("uri") != endpoints.CURRENT_LP_CHANGE_NOTIFICATION:
            return
        self._record_payload(event.get("data"))

    def tick(self) -> None:
        now = self._now()
        if self._initial_trace_import_pending:
            # Ao conectar depois da tela de fim, o endpoint em memória pode
            # já ter expirado, mas o cliente pode ter acabado de gravar o
            # mesmo envelope no trace. Fazemos essa varredura uma vez; os
            # ciclos seguintes continuam leves e o pós-jogo já tem a sua
            # própria importação periódica abaixo.
            self._initial_trace_import_pending = False
            self._announce(self._history.import_trace_logs())

        if self._snapshot_capture_pending and self._phase in SNAPSHOT_START_PHASES:
            self._capture_snapshot_if_due()

        capturing = self._deadline is not None
        if capturing and now >= self._deadline:
            self._deadline = None
            capturing = False
        if capturing and now >= self._next_trace_import:
            self._next_trace_import = now + TRACE_IMPORT_INTERVAL
            self._announce(self._history.import_trace_logs())
        if now >= self._next_poll:
            self._next_poll = now + (
                LP_POLL_INTERVAL if capturing else LP_IDLE_POLL_INTERVAL
            )
            self._poll_current_notification()
        # A comparaÃ§Ã£o tambÃ©m roda no lobby/ChampSelect. Isso recupera um
        # snapshot persistido quando o app sÃ³ foi reaberto depois do fim.
        if (
            self._snapshot is not None
            and now >= self._next_snapshot_poll
            and (self._fallback_not_before is None or now >= self._fallback_not_before)
        ):
            self._next_snapshot_poll = now + SNAPSHOT_POLL_INTERVAL
            self._derive_snapshot_change()

    def _poll_current_notification(self) -> None:
        """Registra somente o aviso oficial que o cliente ainda mantém vivo."""

        try:
            payload = self._client.get(endpoints.CURRENT_LP_CHANGE_NOTIFICATION)
        except ClientClosed:
            raise
        except LcuError:
            return
        self._record_payload(payload)

    def _derive_snapshot_change(self) -> None:
        """Derive PDL only when the local before/after proof is complete."""

        snapshot = self._snapshot
        if snapshot is None:
            return
        puuid = _current_puuid(self._client)
        # The persisted file is local to the machine, not to a single
        # account. Never combine a snapshot from one account with another.
        if puuid != snapshot.puuid:
            return
        try:
            ranked = self._client.get(endpoints.CURRENT_RANKED_STATS)
        except ClientClosed:
            raise
        except LcuError:
            return
        after = _ranked_queue_state(ranked, snapshot.queue_id)
        if after is None:
            return
        games = _recent_ranked_games(self._client, puuid)
        if games is None:
            return
        new_games = tuple(
            game for game in games if game.game_id not in snapshot.game_ids
        )
        # A single new ranked row from the same queue is required. Any
        # ambiguity (two games, another queue, a malformed list) remains
        # unavailable instead of becoming an estimate.
        if len(new_games) != 1 or new_games[0].queue_id != snapshot.queue_id:
            return
        game = new_games[0]
        # The endpoint/event confirmation is still the primary source. If
        # it arrived first for this exact game, discard only this snapshot.
        if self._history.change_for(game.game_id) is not None:
            self._clear_snapshot(snapshot)
            return
        if (
            after.tier != snapshot.tier
            or after.division != snapshot.division
            or after.wins < snapshot.wins
            or after.losses < snapshot.losses
            or (after.wins - snapshot.wins) + (after.losses - snapshot.losses) != 1
        ):
            # Promotion and demotion are intentionally left to the official
            # event: subtraction is not exact across a rank transition.
            return
        change = LpChange(
            game_id=game.game_id,
            queue_id=snapshot.queue_id,
            delta=after.league_points - snapshot.league_points,
            league_points=after.league_points,
            tier=after.tier,
            division=after.division,
            source=LP_SOURCE_LOCAL_SNAPSHOT,
        )
        self._announce(self._history.record_many((change,)))
        self._clear_snapshot(snapshot)

    def _clear_snapshot(self, snapshot: _RankedSnapshot) -> None:
        self._history.clear_pending_snapshot(snapshot)
        if self._snapshot == snapshot:
            self._snapshot = None


def format_lp_delta(delta: int | None) -> str:
    """Texto curto e inequívoco para a lista: ``+21 PDL`` ou ``−18 PDL``."""

    if delta is None:
        return "PDL não registrado"
    sign = "+" if delta > 0 else "−" if delta < 0 else "±"
    return f"{sign}{abs(delta)} PDL"
