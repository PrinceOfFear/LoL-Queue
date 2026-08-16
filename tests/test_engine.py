import pytest

from lolqueue.config import Config
from lolqueue.core.engine import MAX_FAILURES, Engine
from lolqueue.core.phases import GameflowPhase
from lolqueue.lcu import endpoints
from lolqueue.lcu.client import ClientClosed
from tests.fakes import FakeLcuClient


def make_engine(config=None, responses=None, failures=None, closed=False):
    client = FakeLcuClient(responses=responses, failures=failures, closed=closed)
    engine = Engine(client, config or Config())
    engine.set_enabled(True)
    return engine, client


LOBBY_READY = {endpoints.LOBBY: {"canStartActivity": True}}


def test_accepts_ready_check():
    engine, client = make_engine()
    engine.handle_phase(GameflowPhase.READY_CHECK)
    assert endpoints.READY_CHECK_ACCEPT in client.paths("POST")


def test_disabled_engine_does_nothing():
    engine, client = make_engine()
    engine.set_enabled(False)
    engine.handle_phase(GameflowPhase.READY_CHECK)
    assert client.calls == []


def test_auto_accept_off_means_no_accept():
    engine, client = make_engine(Config(auto_accept=False))
    engine.handle_phase(GameflowPhase.READY_CHECK)
    assert client.calls == []


def test_starts_queue_in_lobby_when_auto_queue_on():
    engine, client = make_engine(Config(auto_queue=True), responses=LOBBY_READY)
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_does_not_start_queue_when_not_allowed_to():
    engine, client = make_engine(
        Config(auto_queue=True),
        responses={endpoints.LOBBY: {"canStartActivity": False}},
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.MATCHMAKING_SEARCH not in client.paths("POST")


def test_missing_permission_key_does_not_block_the_user():
    engine, client = make_engine(
        Config(auto_queue=True), responses={endpoints.LOBBY: {}}
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_enabling_the_engine_inside_a_lobby_starts_the_queue():
    """Apertar INICIAR já dentro do lobby precisa valer.

    `handle_phase` só roda em transições de fase. Sem reavaliar no tick,
    quem liga o motor sem sair do lobby espera para sempre.
    """
    client = FakeLcuClient(responses=LOBBY_READY)
    engine = Engine(client, Config(auto_queue=True))
    engine.handle_phase(GameflowPhase.LOBBY)
    assert client.calls == []

    engine.set_enabled(True)
    engine.tick()
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_turning_auto_queue_on_inside_a_lobby_starts_the_queue():
    """Marcar a opção com o motor já ligado também precisa valer."""
    config = Config(auto_queue=False)
    engine, client = make_engine(config, responses=LOBBY_READY)
    engine.handle_phase(GameflowPhase.LOBBY)
    engine.tick()
    assert client.calls == []

    config.auto_queue = True
    engine.tick()
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_auto_queue_off_means_no_search():
    engine, client = make_engine(Config(auto_queue=False), responses=LOBBY_READY)
    engine.handle_phase(GameflowPhase.LOBBY)
    assert client.calls == []


@pytest.mark.parametrize(
    "phase",
    [
        GameflowPhase.END_OF_GAME,
        GameflowPhase.PRE_END_OF_GAME,
        GameflowPhase.WAITING_FOR_STATS,
    ],
)
def test_play_again_closes_the_loop(phase):
    engine, client = make_engine(Config(auto_queue=True))
    engine.handle_phase(phase)
    assert endpoints.PLAY_AGAIN in client.paths("POST")


@pytest.mark.parametrize(
    "phase",
    [
        GameflowPhase.NONE,
        GameflowPhase.MATCHMAKING,
        GameflowPhase.IN_PROGRESS,
        GameflowPhase.GAME_START,
        GameflowPhase.RECONNECT,
        GameflowPhase.UNKNOWN,
    ],
)
def test_idle_phases_trigger_nothing(phase):
    engine, client = make_engine(Config(auto_queue=True, auto_accept=True))
    engine.handle_phase(phase)
    assert client.calls == []


def test_successful_action_runs_only_once_per_phase():
    engine, client = make_engine()
    engine.handle_phase(GameflowPhase.READY_CHECK)
    for _ in range(5):
        engine.tick()
    assert len(client.paths("POST")) == 1


def test_transient_failure_is_retried_on_the_next_tick():
    engine, client = make_engine(failures={endpoints.READY_CHECK_ACCEPT})
    engine.handle_phase(GameflowPhase.READY_CHECK)
    client.failures.clear()
    engine.tick()
    assert len(client.paths("POST")) == 2


def test_backoff_stops_retrying_after_three_failures():
    engine, client = make_engine(failures={endpoints.READY_CHECK_ACCEPT})
    engine.handle_phase(GameflowPhase.READY_CHECK)
    for _ in range(8):
        engine.tick()
    assert len(client.paths("POST")) == MAX_FAILURES


def test_leaving_the_phase_clears_the_backoff():
    engine, client = make_engine(failures={endpoints.READY_CHECK_ACCEPT})
    engine.handle_phase(GameflowPhase.READY_CHECK)
    for _ in range(8):
        engine.tick()
    engine.handle_phase(GameflowPhase.NONE)
    engine.handle_phase(GameflowPhase.READY_CHECK)
    assert len(client.paths("POST")) == MAX_FAILURES + 1


def test_client_closed_propagates_to_the_watcher():
    engine, _ = make_engine(closed=True)
    with pytest.raises(ClientClosed):
        engine.handle_phase(GameflowPhase.READY_CHECK)


def test_failures_are_logged_not_swallowed():
    messages = []
    client = FakeLcuClient(failures={endpoints.READY_CHECK_ACCEPT})
    engine = Engine(client, Config(), log=messages.append)
    engine.set_enabled(True)
    engine.handle_phase(GameflowPhase.READY_CHECK)
    assert messages


def test_champ_select_delegates_to_the_controller():
    class Spy:
        def __init__(self):
            self.reset_calls = 0

        def reset(self):
            self.reset_calls += 1

        def tick(self):
            pass

    spy = Spy()
    engine, _ = make_engine()
    engine.set_champ_select(spy)
    engine.handle_phase(GameflowPhase.CHAMP_SELECT)
    assert spy.reset_calls == 1


def test_champ_select_without_controller_does_not_crash():
    engine, _ = make_engine()
    engine.handle_phase(GameflowPhase.CHAMP_SELECT)
