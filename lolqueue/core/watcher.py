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
                client = LcuClient(credentials)
                self._engine = self._engine_factory(client)
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
