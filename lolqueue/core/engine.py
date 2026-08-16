from __future__ import annotations

from typing import Callable, Protocol

from ..config import Config
from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from .phases import END_PHASES, GameflowPhase

MAX_FAILURES = 3


class ChampSelectController(Protocol):
    def reset(self) -> None: ...
    def tick(self) -> None: ...


class Engine:
    """Traduz transições de fase em chamadas à LCU API.

    Não depende de Qt. Toda ação passa pela trava `enabled`.

    A ação escolhida por `handle_phase` vira *pendente* e é retentada nos
    ticks seguintes até ter sucesso ou estourar MAX_FAILURES — uma falha
    de rede isolada não pode custar a partida. Sucesso limpa a pendência,
    então nada roda duas vezes na mesma fase.
    """

    def __init__(
        self,
        client,
        config: Config,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._log = log or (lambda message: None)
        self._enabled = False
        self._phase = GameflowPhase.UNKNOWN
        self._champ_select: ChampSelectController | None = None
        self._pending: Callable[[], None] | None = None
        self._action_failures = 0
        self._champ_failures = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
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
        return None

    def _clear_pending(self) -> None:
        self._pending = None
        self._action_failures = 0
        self._champ_failures = 0

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

    def _start_queue(self) -> None:
        lobby = self._client.get(endpoints.LOBBY) or {}
        if isinstance(lobby, dict) and lobby.get("canStartActivity") is False:
            self._log("Sem permissão para iniciar a fila neste lobby.")
            return
        self._client.post(endpoints.MATCHMAKING_SEARCH)
        self._log("Entrando na fila.")

    def _play_again(self) -> None:
        self._client.post(endpoints.PLAY_AGAIN)
        self._log("Voltando ao lobby.")
