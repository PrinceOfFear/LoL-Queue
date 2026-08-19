from __future__ import annotations

import time
from functools import partial
from typing import Callable, Protocol

from ..config import Config, queue_name
from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from .phases import END_PHASES, GameflowPhase

MAX_FAILURES = 3

#: Estados em que a busca está de pé. Qualquer outro quer dizer fila
#: parada — inclusive "Error", que o cliente deixa grudado.
LIVE_SEARCH_STATES = frozenset({"Searching", "Found"})

#: Estados que deixam resto no cliente. Enquanto a busca estragada não
#: for cancelada, ele recusa uma nova entrada — por isso não basta
#: mandar procurar de novo.
STUCK_SEARCH_STATES = frozenset(
    {
        "Error",
        "ServiceError",
        "ServiceShutdown",
        "Canceled",
        "AbandonedLowPriorityQueue",
    }
)

#: Fases em que se cobra que a busca esteja viva. Fora delas o jogador
#: está em seleção ou em partida, e não há fila alguma a vigiar.
SEARCH_PHASES = (GameflowPhase.LOBBY, GameflowPhase.MATCHMAKING)

#: Intervalo entre conferências do estado da busca. Espaçado de propósito:
#: o polling roda a cada 0,25 s e essa pergunta não precisa dessa pressa.
SEARCH_CHECK_SECONDS = 3.0


class ChampSelectController(Protocol):
    def reset(self) -> None: ...
    def tick(self) -> None: ...


class Engine:
    """Traduz transições de fase em chamadas à LCU API.

    Não depende de Qt. Toda ação passa pela trava `enabled`.

    A ação escolhida por `handle_phase` vira *pendente* e é retentada nos
    ticks seguintes até ter sucesso ou estourar MAX_FAILURES — uma falha
    de rede isolada não pode custar a partida. Sucesso marca `_acted`,
    então nada roda duas vezes na mesma fase.

    O tick também *reavalia* a fase atual enquanto nada foi feito nela.
    Sem isso, ligar o motor ou marcar uma opção sem sair do lobby não
    teria efeito, porque `handle_phase` só roda em transições.

    E vigia o estado da busca, porque nem toda parada troca de fase: o
    cliente erra ao procurar partida e fica parado no mesmo lugar.
    """

    def __init__(
        self,
        client,
        config: Config,
        log: Callable[[str], None] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._config = config
        self._log = log or (lambda message: None)
        self._now = now
        self._enabled = False
        self._phase = GameflowPhase.UNKNOWN
        self._champ_select: ChampSelectController | None = None
        self._pending: Callable[[], None] | None = None
        self._acted = False
        self._action_failures = 0
        self._champ_failures = 0
        self._checked_search = 0.0
        self._search_stalled = False
        # Convidado = está numa sala de outra pessoa. Fica lembrado
        # depois que a sala some: é justamente ao voltar para a tela
        # inicial que o app abriria uma sala própria e entraria na fila
        # sozinho, largando o grupo do amigo.
        self._guest = False
        self._warned_guest = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._checked_search = 0.0
        self._search_stalled = False
        # Ligar o motor é o jogador dizendo o que quer agora; o que
        # aconteceu antes disso não vale mais.
        self._guest = False
        self._warned_guest = False
        self._clear_pending()

    def set_champ_select(self, controller: ChampSelectController | None) -> None:
        self._champ_select = controller

    def handle_phase(self, phase: GameflowPhase) -> None:
        """Reage a uma transição de fase."""
        if phase is not self._phase:
            self._clear_pending()
        self._phase = phase

        if not self._enabled:
            return

        if phase is GameflowPhase.CHAMP_SELECT and self._champ_select is not None:
            self._champ_select.reset()

        self._pending = self._action_for(phase)
        self._run_pending()

    def tick(self) -> None:
        """Chamado a cada ciclo de polling, para trabalho contínuo."""
        if not self._enabled:
            return
        self._watch_search()
        self._rearm()
        self._run_pending()
        if self._phase is GameflowPhase.CHAMP_SELECT and self._champ_select is not None:
            self._run_champ_select()

    def _action_for(self, phase: GameflowPhase) -> Callable[[], None] | None:
        if phase is GameflowPhase.READY_CHECK and self._config.auto_accept:
            return self._accept_ready_check
        if phase is GameflowPhase.LOBBY and self._config.auto_queue:
            return self._start_queue
        if phase in END_PHASES and self._config.auto_queue:
            return self._play_again
        if phase is GameflowPhase.NONE and self._config.auto_queue:
            return self._open_lobby
        return None

    def _clear_pending(self) -> None:
        self._pending = None
        self._acted = False
        self._action_failures = 0
        self._champ_failures = 0

    def _rearm(self) -> None:
        """Reavalia a fase atual quando ainda não agimos nela.

        Não mexe numa pendência viva (seria perder as retentativas) nem
        ressuscita uma ação que já desistiu por MAX_FAILURES.
        """
        if self._pending is not None or self._acted:
            return
        if self._action_failures >= MAX_FAILURES:
            return
        self._pending = self._action_for(self._phase)

    def _watch_search(self) -> None:
        """Retoma a fila que morreu sem o cliente trocar de fase.

        O LoL erra ao procurar partida de vez em quando: a busca cai, o
        cliente guarda o estado estragado e não sai mais dele sozinho —
        vi `searchState` em "Error" persistindo até sem lobby nenhum.
        Nenhuma transição avisa, e `_acted` impede uma segunda tentativa
        na mesma fase, então sem isto o app espera para sempre.
        """
        if not self._config.auto_queue or self._phase not in SEARCH_PHASES:
            return
        # A busca de uma sala alheia não é nossa para retomar.
        if self._guest and self._config.queue_only_as_host:
            return
        now = self._now()
        if now - self._checked_search < SEARCH_CHECK_SECONDS:
            return
        self._checked_search = now

        state = self._search_state()
        if not isinstance(state, dict):
            return
        name = state.get("searchState")

        if name in LIVE_SEARCH_STATES:
            if self._search_stalled:
                self._search_stalled = False
                self._log("Fila retomada.")
            return

        if not self._search_stalled:
            self._search_stalled = True
            self._log(f"Busca parada ({name}) — retomando a fila.")
            for detail in self._search_errors(state):
                self._log(detail)

        if name in STUCK_SEARCH_STATES and not self._cancel_search():
            return

        # Insistir daqui em diante é silencioso: o episódio já foi contado
        # e a fila parada repetiria a mesma linha a cada poucos segundos.
        self._acted = False
        self._action_failures = 0
        self._pending = partial(self._start_queue, announce=False)

    def _search_state(self) -> object:
        """Estado da busca, ou None se nem isso responder.

        Uma falha aqui é diagnóstico perdido, não motivo para derrubar o
        tick: se o cliente está mesmo ruim, a ação pendente falha sozinha
        e é ela quem reporta.
        """
        try:
            return self._client.get(endpoints.MATCHMAKING_SEARCH_STATE)
        except ClientClosed:
            raise
        except LcuError:
            return None

    def _cancel_search(self) -> bool:
        """Limpa a busca estragada. Sem isso o cliente recusa a próxima."""
        try:
            self._client.delete(endpoints.MATCHMAKING_SEARCH)
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não consegui cancelar a busca: {exc}")
            return False
        return True

    @staticmethod
    def _search_errors(state: dict) -> list[str]:
        """Motivos que o cliente anexou à busca, quando anexa algum.

        Costuma vir vazio mesmo em "Error", então isto é um extra — a
        parada é reportada de qualquer jeito.
        """
        details = []
        for error in state.get("errors") or []:
            if not isinstance(error, dict):
                continue
            text = error.get("message") or error.get("errorType")
            if text:
                details.append(f"Cliente: {text}")
        return details

    def _run_pending(self) -> None:
        """Executa a ação pendente. ClientClosed sobe para o watcher."""
        action = self._pending
        if action is None:
            return
        try:
            action()
        except ClientClosed:
            raise
        except LcuError as exc:
            self._action_failures += 1
            self._log(
                f"Falha em {self._phase.value} "
                f"({self._action_failures}/{MAX_FAILURES}): {exc}"
            )
            if self._action_failures >= MAX_FAILURES:
                self._pending = None
                self._log(
                    f"Desistindo de agir em {self._phase.value} até a fase mudar."
                )
        else:
            self._pending = None
            self._acted = True
            self._action_failures = 0

    def _run_champ_select(self) -> None:
        if self._champ_failures >= MAX_FAILURES:
            return
        try:
            self._champ_select.tick()
        except ClientClosed:
            raise
        except LcuError as exc:
            self._champ_failures += 1
            self._log(
                f"Falha na seleção de campeões "
                f"({self._champ_failures}/{MAX_FAILURES}): {exc}"
            )
        else:
            self._champ_failures = 0

    def _accept_ready_check(self) -> None:
        self._client.post(endpoints.READY_CHECK_ACCEPT)
        self._log("Partida aceita.")

    def _start_queue(self, announce: bool = True) -> None:
        """Entra na fila. Calada quando é retomada de uma busca parada.

        `announce` existe só pelo registro: a retomada insiste de poucos
        em poucos segundos, e anunciar cada tentativa afogaria o resto.
        """
        lobby = self._client.get(endpoints.LOBBY) or {}
        if isinstance(lobby, dict):
            self._note_role(lobby)
        if self._holding_back():
            return
        if isinstance(lobby, dict) and lobby.get("canStartActivity") is False:
            if announce:
                self._log("Sem permissão para iniciar a fila neste lobby.")
            return
        self._client.post(endpoints.MATCHMAKING_SEARCH)
        if announce:
            self._log("Entrando na fila.")

    def _note_role(self, lobby: dict) -> None:
        """Anota se a sala é nossa ou de outra pessoa.

        Formato inesperado conta como sala nossa: trancar a fila de quem
        joga sozinho por causa de um campo que sumiu seria bem pior do
        que deixar passar.
        """
        member = lobby.get("localMember")
        is_leader = (member or {}).get("isLeader", True)
        self._guest = not is_leader
        if is_leader:
            self._warned_guest = False

    def _holding_back(self) -> bool:
        """True quando a sala é de outro e o jogador pediu para não mexer."""
        if not (self._guest and self._config.queue_only_as_host):
            return False
        if not self._warned_guest:
            self._warned_guest = True
            self._log(
                "Você não é o dono da sala — deixo a fila com quem é e "
                "sigo só aceitando, banindo e escolhendo."
            )
        return True

    def _play_again(self) -> None:
        self._client.post(endpoints.PLAY_AGAIN)
        self._log("Voltando ao lobby.")

    def _open_lobby(self) -> None:
        """Reabre o lobby quando o cliente larga o jogador na tela inicial.

        O `play-again` nem sempre recria o lobby: em algumas partidas o
        cliente volta para a tela inicial, e ali não existe lobby de onde
        entrar na fila. Como a fase para de mudar, a fila contínua morria
        calada exatamente aí.

        Não é preciso conferir se já há um lobby: se houvesse, a fase
        seria `Lobby` e esta ação nem seria escolhida.
        """
        if self._holding_back():
            return
        self._client.post(
            endpoints.LOBBY, json={"queueId": self._config.queue_id}
        )
        self._log(f"Sem lobby — abrindo {queue_name(self._config.queue_id)}.")
