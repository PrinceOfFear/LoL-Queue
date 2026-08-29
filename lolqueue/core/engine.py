from __future__ import annotations

import random
import time
from functools import partial
from typing import Callable, Protocol

from ..config import UNSELECTED, Config, preference_name, queue_name
from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from .delay import Rng, sample
from .phases import END_PHASES, PLAYING_PHASES, GameflowPhase

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

#: Janela depois da partida em que a recusa do cliente é esperada, não
#: erro. Ao voltar da partida o cliente ainda responde 400 com
#: ALREADY_IN_GAME por alguns segundos, e o registro mostrou isso durar
#: de 5 a 9. Quarenta e cinco dá margem larga para um cliente lento sem
#: engolir uma falha de verdade para sempre.
POSTGAME_GRACE_SECONDS = 45.0

#: Intervalo entre tentativas enquanto o cliente ainda está assentando.
#: O polling roda a cada 0,2 s: sem isto as três chances queimavam em
#: dois segundos e o app desistia antes de o cliente ficar pronto.
QUEUE_RETRY_SECONDS = 2.0


#: Fases em que o silêncio da seleção já não serve. Devolver as opções
#: aqui é o que impede o app de deixar o chat desligado para sempre.
MUTE_OVER_PHASES = END_PHASES | {GameflowPhase.NONE, GameflowPhase.LOBBY}


class MuteController(Protocol):
    def restore(self) -> bool: ...


class JungleWatch(Protocol):
    def start(self) -> bool: ...
    def stop(self) -> None: ...


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
        rng: Rng = random.uniform,
    ) -> None:
        self._client = client
        self._config = config
        self._log = log or (lambda message: None)
        self._now = now
        self._rng = rng
        self._enabled = False
        self._phase = GameflowPhase.UNKNOWN
        self._champ_select: ChampSelectController | None = None
        self._antitoxic: MuteController | None = None
        self._jungle: JungleWatch | None = None
        self._game_sync = None
        self._pending: Callable[[], None] | None = None
        self._acted = False
        self._action_failures = 0
        self._champ_failures = 0
        # Última dupla de rotas mandada ao cliente. Guardada pela
        # vida do motor, e não por fase: um pedido recusado pelo
        # cliente continua recusado no lobby seguinte, e insistir
        # só encheria o registro. Mexer na escolha muda o alvo e
        # libera uma tentativa nova.
        self._positions_asked: tuple[str, str] | None = None
        self._checked_search = 0.0
        self._search_stalled = False
        # Se a parada chegou a ser anunciada. "Fila retomada" sem a
        # linha da parada antes é resposta a pergunta que ninguém fez.
        self._stall_announced = False
        # Instante em que esta partida pode ser aceita. Sorteado uma vez
        # por checagem de prontidão e zerado ao trocar de fase.
        self._accept_at: float | None = None
        # Fim da última partida, e o instante em que a fila pode começar.
        # Sobrevivem à troca de fase de propósito: a espera nasce em
        # EndOfGame e precisa valer quando o lobby aparece.
        self._match_ended_at: float | None = None
        self._queue_at: float | None = None
        self._retry_at = 0.0
        self._settling = False
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
        # Desligar o motor devolve o chat: quem para o app não deve
        # continuar mudo sem saber por quê.
        if not enabled and self._antitoxic is not None:
            self._antitoxic.restore()
        self._clear_pending()

    def set_champ_select(self, controller: ChampSelectController | None) -> None:
        self._champ_select = controller

    def set_antitoxic(self, guard: MuteController | None) -> None:
        self._antitoxic = guard

    def set_jungle_watch(self, watch: JungleWatch | None) -> None:
        self._jungle = watch

    def set_game_sync(self, sync) -> None:
        """Quem copia as configurações do jogo entre contas.

        Mora aqui porque o motor é o único objeto que roda na thread da
        vigia com o cliente da LCU na mão — não porque a cópia tenha a
        ver com fila automática. Ver `handle_identity` e `tick`.
        """
        self._game_sync = sync

    def handle_identity(self, identity) -> None:
        """Outra conta entrou no cliente."""
        if self._game_sync is not None:
            self._game_sync.account_arrived(identity)

    def handle_phase(self, phase: GameflowPhase) -> None:
        """Reage a uma transição de fase."""
        if phase is not self._phase:
            self._clear_pending()
        self._phase = phase

        if self._antitoxic is not None and phase in MUTE_OVER_PHASES:
            # Fora de qualquer proteção do motor ligado: a partida
            # acabou, e o que era do jogador volta a ser dele.
            self._antitoxic.restore()

        if self._jungle is not None:
            # Fora da trava do motor de propósito: quem quer só o aviso
            # do jungler não deveria ser obrigado a deixar a fila
            # automática ligada para tê-lo. Só a partida na tela e a
            # opção marcada decidem.
            if phase in PLAYING_PHASES:
                if getattr(self._config, "jungle_callouts", False):
                    self._jungle.start()
            else:
                # Inclui sair da partida por qualquer porta: fim normal,
                # queda de conexão ou volta ao lobby. Nenhuma delas pode
                # deixar o app capturando tela.
                self._jungle.stop()

        if phase is GameflowPhase.CHAMP_SELECT and self._champ_select is not None:
            # Também com o motor desligado: o controlador é reaproveitado
            # entre seleções da mesma conexão, então sem isto religar a
            # automação no meio de uma seleção nova herdava trava e prévia
            # de campeão da seleção anterior, já encerrada.
            self._champ_select.reset()

        if not self._enabled:
            return

        if phase in END_PHASES:
            # Marcado mesmo com a fila automática desligada: se ela for
            # ligada logo depois, a espera ainda vale.
            self._note_match_end()

        self._pending = self._action_for(phase)
        self._run_pending()

    def tick(self) -> None:
        """Chamado a cada ciclo de polling, para trabalho contínuo."""
        if self._game_sync is not None:
            # Antes da trava do motor, como o aviso do jungler: copiar
            # as configurações do jogo não é fila automática, e exigir
            # o motor ligado para isso não faria sentido para quem só
            # quer entrar na conta de outro e achar as teclas no lugar.
            self._game_sync.tick()
        if not self._enabled:
            return
        self._watch_search()
        self._rearm()
        self._run_pending()
        if self._phase is GameflowPhase.CHAMP_SELECT and self._champ_select is not None:
            self._run_champ_select()

    def _action_for(self, phase: GameflowPhase) -> Callable[[], None] | None:
        if phase is GameflowPhase.READY_CHECK and self._config.auto_accept:
            if self._waiting_to_accept():
                return None
            return self._accept_ready_check
        if phase is GameflowPhase.LOBBY and self._config.auto_queue:
            if self._waiting_after_game():
                return None
            return self._start_queue
        if phase in END_PHASES and self._config.auto_queue:
            return self._play_again
        if phase is GameflowPhase.NONE and self._config.auto_queue:
            return self._open_lobby
        return None

    def _clear_pending(self) -> None:
        self._pending = None
        self._accept_at = None
        self._retry_at = 0.0
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
        # Durante a espera ninguém mexe: a busca "parada" logo depois da
        # partida é o próprio cliente encerrando, e cutucá-la aqui era
        # metade do barulho que aparecia no registro.
        if self._waiting_after_game():
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
                if self._stall_announced:
                    self._stall_announced = False
                    self._log("Fila retomada.")
            return

        if not self._search_stalled:
            self._search_stalled = True
            # Logo depois da partida a busca "parada" é o próprio cliente
            # encerrando a anterior. A retomada acontece igual; o que não
            # cabe é chamar de problema o que é rotina.
            if not self._in_postgame_grace():
                self._stall_announced = True
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
        if self._now() < self._retry_at:
            return
        try:
            action()
        except ClientClosed:
            raise
        except LcuError as exc:
            if self._in_postgame_grace():
                # O cliente ainda está soltando a partida anterior. Isso
                # não é falha nossa e não pode gastar as tentativas —
                # era exatamente assim que a fila contínua morria.
                self._retry_at = self._now() + QUEUE_RETRY_SECONDS
                if not self._settling:
                    self._settling = True
                    self._log(
                        "O cliente ainda está encerrando a partida "
                        "— tento de novo em instantes."
                    )
                return
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
            self._retry_at = 0.0
            self._settling = False

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

    def _note_match_end(self) -> None:
        """Registra que uma partida acabou agora."""
        self._match_ended_at = self._now()
        self._queue_at = None
        self._settling = False

    def _in_postgame_grace(self) -> bool:
        """True enquanto a recusa do cliente ainda é o normal do pós-jogo."""
        if self._match_ended_at is None:
            return False
        return self._now() - self._match_ended_at < POSTGAME_GRACE_SECONDS

    def _waiting_after_game(self) -> bool:
        """Segura a fila pelo tempo que o usuário escolheu.

        O cliente recusa a fila enquanto encerra a partida anterior, e
        insistir contra isso só rendia erro no registro. Esperar não é
        perda: a fila não andaria mesmo.
        """
        if self._match_ended_at is None:
            return False
        if self._queue_at is None:
            wait = sample(
                self._config.postgame_delay_min,
                self._config.postgame_delay_max,
                self._rng,
            )
            self._queue_at = self._match_ended_at + wait
            if wait:
                self._log(f"Partida encerrada — entrando na fila em {wait:.0f}s.")
        return self._now() < self._queue_at

    def _waiting_to_accept(self) -> bool:
        """Segura o aceite pelo tempo sorteado para esta partida.

        Aceitar no mesmo instante em que a fase muda não deixa janela
        nenhuma para quem mudou de ideia. Devolver `None` de
        `_action_for` enquanto a espera corre reaproveita o `_rearm`,
        que já reavalia a fase a cada tick — uma segunda máquina de
        espera ao lado dela só teria como discordar.

        Nada aqui protege de nada: a Riot tolera o aceite automático. O
        que o atraso compra é tempo de reagir.
        """
        if self._accept_at is None:
            wait = sample(
                self._config.accept_delay_min,
                self._config.accept_delay_max,
                self._rng,
            )
            self._accept_at = self._now() + wait
            if wait:
                self._log(f"Partida encontrada — aceitando em {wait:.1f}s.")
        return self._now() < self._accept_at

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
        if isinstance(lobby, dict):
            self._push_positions(lobby)
        if isinstance(lobby, dict) and lobby.get("canStartActivity") is False:
            if announce:
                self._log("Sem permissão para iniciar a fila neste lobby.")
            return
        self._client.post(endpoints.MATCHMAKING_SEARCH)
        # A retomada de uma busca parada entra calada, senão repetiria a
        # mesma linha de poucos em poucos segundos. Mas quando houve uma
        # espera anunciada, ficar calado agora vira dúvida: entrou ou
        # travou? Então o desfecho sai de qualquer jeito.
        esperou = self._queue_at is not None
        # A partida anterior deixou de importar: sem isto a próxima vez
        # que o lobby aparecesse herdaria a espera desta.
        self._match_ended_at = None
        self._queue_at = None
        if announce or esperou:
            self._log("Entrando na fila.")

    def _push_positions(self, lobby: dict) -> None:
        """Pede as rotas escolhidas nos Ajustes, antes de entrar na fila.

        Só quando há rota pedida e a fila tem onde guardá-la: em ARAM ou
        no modo cego o cliente não tem esse campo. Vazio quer dizer "não
        mexe", e é o padrão — quem nunca abriu a tela continua com o que
        escolheu no cliente.

        Uma falha aqui não pode custar a fila. Esta chamada é a única do
        app que escreve numa rota que a sonda não confirma (ela só lê), e
        `_start_queue` roda dentro do contador de falhas: deixar o erro
        subir trancaria a entrada na fila por causa de uma preferência.
        Então o erro é anotado e a vida segue.

        A tentativa fica guardada para não repetir: sem isso um pedido
        recusado voltaria a cada retomada da busca, enchendo o registro.
        Mudar a escolha na tela muda o alvo e libera uma nova tentativa.
        """
        if not self._config.wants_positions():
            return
        wanted = (
            self._config.primary_position.upper(),
            (self._config.secondary_position or UNSELECTED).upper(),
        )
        member = lobby.get("localMember") or {}
        current = (
            str(member.get("firstPositionPreference") or UNSELECTED).upper(),
            str(member.get("secondPositionPreference") or UNSELECTED).upper(),
        )
        if wanted == current or wanted == self._positions_asked:
            return
        self._positions_asked = wanted
        try:
            self._client.put(
                endpoints.LOBBY_POSITION_PREFERENCES,
                json={"firstPreference": wanted[0], "secondPreference": wanted[1]},
            )
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não consegui pedir as rotas: {exc}")
            return
        self._log(f"Rotas pedidas: {self._positions_label()}.")

    def _positions_label(self) -> str:
        primary = preference_name(self._config.primary_position)
        secondary = self._config.secondary_position
        if not secondary:
            return primary
        return f"{primary} e {preference_name(secondary)}"

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
        # Conta a espera daqui, e não da tela de estatísticas: é agora
        # que o cliente começa a soltar a partida.
        self._note_match_end()
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
