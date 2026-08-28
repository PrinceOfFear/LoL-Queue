from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuClient, LcuError
from ..lcu.credentials import discover
from .phases import GameflowPhase, PhaseTracker

POLL_INTERVAL = 0.25
RECONNECT_INTERVAL = 2.0


class ConnectionState:
    """Estado de conexão e a cadência de polling que ele implica."""

    def __init__(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def interval(self) -> float:
        return POLL_INTERVAL if self._connected else RECONNECT_INTERVAL

    def set_connected(self, connected: bool) -> bool:
        """Aplica o estado. Devolve True se mudou."""
        if connected == self._connected:
            return False
        self._connected = connected
        return True


class PhaseWatcher(QThread):
    """Consulta a fase do jogo e emite sinais Qt.

    Dono único das chamadas HTTP: o polling de fase e o da seleção de
    campeões se intercalam nesta thread, nunca em duas.

    A espera entre ciclos usa um Event em vez de sleep, para que `stop()`
    acorde a thread na hora e o fechamento da janela não trave.
    """

    phase_changed = Signal(str)
    connection_changed = Signal(bool)
    message = Signal(str)
    #: O campeão que a lista de prioridade escolheria agora, ou `None`
    #: quando não há prévia (fora da seleção, ou sem opção sobrando).
    #: `object` porque `Signal(int)` não aceita `None` na travessia Qt.
    predicted_pick_changed = Signal(object)
    #: A rota que o cliente atribuiu ao jogador nesta seleção, ou ""
    #: fora dela. É o que diz qual lista de prioridade está valendo, e
    #: portanto qual delas a Central deixa reordenar.
    pick_scope_changed = Signal(str)
    #: As builds de runa que a busca externa trouxe (chaves de
    #: `OPGG_TIERS`) e qual delas está no cliente agora, ou `None`
    #: quando a runa aplicada não veio de nenhuma delas. Vai como
    #: `object` pelo mesmo motivo do sinal acima: a lista pode chegar
    #: vazia e o elo ativo pode ser `None`.
    rune_options_changed = Signal(object, object, object)
    #: O campeão travado, a rota dele e a build inteira que o OP.GG
    #: devolveu — a parte que não se aplica no cliente, só se lê.
    #: `object` porque a build pode vir `None`, quando a consulta
    #: externa falhou ou o modo não tem dados.
    analysis_changed = Signal(object, object, object)

    def __init__(self, engine_factory: Callable[[LcuClient], object]) -> None:
        super().__init__()
        self._engine_factory = engine_factory
        self._running = True
        self._engine = None
        self._wake = threading.Event()

    @property
    def engine(self):
        return self._engine

    def stop(self) -> None:
        self._running = False
        self._wake.set()

    def run(self) -> None:
        state = ConnectionState()
        tracker = PhaseTracker()
        client: LcuClient | None = None

        while self._running:
            if client is None:
                credentials = discover()
                if credentials is None:
                    if state.set_connected(False):
                        self.connection_changed.emit(False)
                    self._wake.wait(state.interval)
                    continue
                try:
                    client = LcuClient(credentials)
                    self._engine = self._engine_factory(client)
                except ClientClosed:
                    # O lockfile já existe, mas a API do LCU ainda não
                    # aceita conexões — corrida comum quando este app já
                    # está de pé fazendo polling antes do cliente do LoL
                    # terminar de subir. Não é fatal: só adia a conexão
                    # pro próximo ciclo, sem matar a thread inteira (senão
                    # só fechar e reabrir o app reconecta).
                    client = None
                    self._engine = None
                    if state.set_connected(False):
                        self.connection_changed.emit(False)
                    self._wake.wait(state.interval)
                    continue
                except LcuError as exc:
                    client = None
                    self._engine = None
                    self.message.emit(str(exc))
                    if state.set_connected(False):
                        self.connection_changed.emit(False)
                    self._wake.wait(state.interval)
                    continue
                tracker.reset()
                if state.set_connected(True):
                    self.connection_changed.emit(True)
                    self.message.emit("Cliente do LoL conectado.")

            try:
                raw = client.get(endpoints.GAMEFLOW_PHASE)
                phase = GameflowPhase.parse(raw)
                if tracker.update(phase):
                    self.phase_changed.emit(phase.value)
                    self._engine.handle_phase(phase)
                else:
                    self._engine.tick()
            except ClientClosed:
                client = None
                self._engine = None
                if state.set_connected(False):
                    self.connection_changed.emit(False)
                    self.message.emit("Cliente do LoL fechado.")
            except LcuError as exc:
                self.message.emit(str(exc))

            self._wake.wait(state.interval)
