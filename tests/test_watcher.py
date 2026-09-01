import lolqueue.core.watcher as watcher_module
from lolqueue.core.watcher import POLL_INTERVAL, RECONNECT_INTERVAL, ConnectionState, PhaseWatcher
from lolqueue.lcu.client import ClientClosed
from lolqueue.lcu.credentials import Credentials


class _FakeClient:
    def get(self, path):
        return "None"  # GameflowPhase.NONE.value — cliente parado no menu


class _FakeEngine:
    def tick(self) -> None:
        pass

    def handle_phase(self, phase) -> None:
        pass


def test_a_failed_first_connection_does_not_kill_the_watcher_thread(monkeypatch):
    """Reproduz o bug: LoL Queue aberto antes do cliente do LoL.

    O lockfile pode existir (`discover()` acha credenciais) antes da API
    do LCU aceitar conexões de verdade — nesse instante, montar o motor
    (`_engine_factory`, que chama `unavailable_queues()`) recebe
    `ClientClosed`. Isso acontecia FORA do try/except de `run()`, matando
    a thread pra sempre: só fechar e reabrir o app criava um `PhaseWatcher`
    novo. O watcher precisa tratar essa falha como "ainda não conectado"
    e tentar de novo no próximo ciclo, sem nunca sair do loop.
    """
    monkeypatch.setattr(watcher_module, "RECONNECT_INTERVAL", 0.0)
    monkeypatch.setattr(
        watcher_module, "discover", lambda: Credentials(port=1, token="t")
    )
    monkeypatch.setattr(watcher_module, "LcuClient", lambda credentials: _FakeClient())

    attempts = []

    def flaky_factory(client):
        attempts.append(client)
        if len(attempts) == 1:
            raise ClientClosed("API do LCU ainda não está pronta")
        watcher._running = False
        return _FakeEngine()

    watcher = PhaseWatcher(flaky_factory)

    watcher.run()

    assert len(attempts) == 2, "o watcher deveria tentar reconectar, não morrer"


def test_starts_disconnected():
    state = ConnectionState()
    assert state.connected is False
    assert state.interval == RECONNECT_INTERVAL


def test_connecting_reports_a_change_once():
    state = ConnectionState()
    assert state.set_connected(True) is True
    assert state.set_connected(True) is False


def test_connected_polls_faster():
    state = ConnectionState()
    state.set_connected(True)
    assert state.interval == POLL_INTERVAL


def test_disconnecting_reports_a_change_and_slows_down():
    state = ConnectionState()
    state.set_connected(True)
    assert state.set_connected(False) is True
    assert state.interval == RECONNECT_INTERVAL


def test_discarding_a_connection_closes_its_engine_resources():
    class EngineWithClose:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    engine = EngineWithClose()
    watcher = PhaseWatcher(lambda _client: engine)
    watcher._engine = engine

    watcher._close_engine()

    assert engine.closed == 1
    assert watcher.engine is None
