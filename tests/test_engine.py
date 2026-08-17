import pytest

from lolqueue.config import Config
from lolqueue.core.engine import MAX_FAILURES, SEARCH_CHECK_SECONDS, Engine
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


def test_the_lobby_is_reopened_when_the_client_drops_to_the_home_screen():
    """O fim da partida às vezes devolve o cliente à tela inicial.

    O `play-again` nem sempre recria o lobby. Quando não recria, não há
    de onde entrar na fila, e a fila contínua morria calada bem ali.
    """
    engine, client = make_engine(Config(auto_queue=True, queue_id=450))
    engine.handle_phase(GameflowPhase.NONE)

    assert client.payloads == [(endpoints.LOBBY, {"queueId": 450})]


def test_reopening_the_lobby_does_not_skip_straight_to_the_queue():
    """Primeiro o lobby existe, depois a fila — nessa ordem."""
    engine, client = make_engine(Config(auto_queue=True))
    engine.handle_phase(GameflowPhase.NONE)

    assert endpoints.MATCHMAKING_SEARCH not in client.paths("POST")


def test_the_home_screen_is_left_alone_when_auto_queue_is_off():
    """Sem fila contínua, abrir lobby sozinho seria invasão pura."""
    engine, client = make_engine(Config(auto_queue=False))
    engine.handle_phase(GameflowPhase.NONE)

    assert client.calls == []


def test_the_reopened_lobby_leads_into_the_queue():
    """O ciclo fecha: tela inicial -> lobby -> fila."""
    engine, client = make_engine(Config(auto_queue=True), responses=LOBBY_READY)
    engine.handle_phase(GameflowPhase.NONE)
    engine.handle_phase(GameflowPhase.LOBBY)

    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


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


SEARCH_STATE = endpoints.MATCHMAKING_SEARCH_STATE


def make_watching_engine(state, phase=GameflowPhase.LOBBY, log=None):
    """Motor em fila contínua, com o relógio na mão.

    Devolve o relógio junto porque a conferência da busca é espaçada no
    tempo: sem adiantá-lo, nenhum tick chega a olhar o estado.
    """
    clock = {"t": 1000.0}
    client = FakeLcuClient(responses={**LOBBY_READY, SEARCH_STATE: state})
    engine = Engine(
        client, Config(auto_queue=True), log=log, now=lambda: clock["t"]
    )
    engine.set_enabled(True)
    engine.handle_phase(phase)
    return engine, client, clock


def test_a_dead_search_is_restarted_without_a_phase_change():
    """O erro do cliente ao procurar partida não troca de fase.

    Foi o que travou o app numa sessão real: o LoL deixou a busca em
    "Error", ninguém saiu do lobby e, como `handle_phase` só dispara em
    transição, o app esperou parado. Só o estado da busca denuncia.
    """
    engine, client, clock = make_watching_engine({"searchState": "Error"})
    assert len(client.paths("POST")) == 1

    clock["t"] += SEARCH_CHECK_SECONDS
    engine.tick()

    assert endpoints.MATCHMAKING_SEARCH in client.paths("DELETE")
    assert len(client.paths("POST")) == 2


def test_a_live_search_is_left_alone():
    """Fila andando não pode ser reiniciada: cairíamos no fim da espera."""
    engine, client, clock = make_watching_engine({"searchState": "Searching"})
    for _ in range(3):
        clock["t"] += SEARCH_CHECK_SECONDS
        engine.tick()

    assert client.paths("DELETE") == []
    assert len(client.paths("POST")) == 1


def test_a_stuck_matchmaking_is_recovered():
    """Fase de fila com a busca morta: nada mais perceberia."""
    engine, client, clock = make_watching_engine(
        {"searchState": "Error"}, phase=GameflowPhase.MATCHMAKING
    )
    assert client.calls == []

    clock["t"] += SEARCH_CHECK_SECONDS
    engine.tick()

    assert endpoints.MATCHMAKING_SEARCH in client.paths("DELETE")
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_a_queue_that_never_started_is_not_cancelled():
    """"Invalid" é o estado de lobby recém-aberto: não há o que cancelar."""
    engine, client, clock = make_watching_engine({"searchState": "Invalid"})
    clock["t"] += SEARCH_CHECK_SECONDS
    engine.tick()

    assert client.paths("DELETE") == []
    assert len(client.paths("POST")) == 2


def test_the_search_state_is_not_polled_on_every_tick():
    """A conferência é barata, mas não precisa correr a cada 0,25 s."""
    engine, client, _ = make_watching_engine({"searchState": "Searching"})
    for _ in range(5):
        engine.tick()

    assert client.paths("GET").count(SEARCH_STATE) == 1


def test_the_watch_is_off_when_auto_queue_is_off():
    client = FakeLcuClient(responses={SEARCH_STATE: {"searchState": "Error"}})
    engine = Engine(client, Config(auto_queue=False))
    engine.set_enabled(True)
    engine.handle_phase(GameflowPhase.LOBBY)
    engine.tick()

    assert client.calls == []


def test_the_stall_is_reported_once_and_so_is_the_recovery():
    """Insistir é silencioso; o que o usuário precisa ver é o episódio.

    Sem isso, uma fila que não volta encheria o registro de linhas
    iguais a cada poucos segundos.
    """
    messages = []
    engine, client, clock = make_watching_engine(
        {
            "searchState": "Error",
            "errors": [{"message": "Falha ao entrar na fila"}],
        },
        log=messages.append,
    )
    for _ in range(3):
        clock["t"] += SEARCH_CHECK_SECONDS
        engine.tick()

    assert len([m for m in messages if "Busca parada" in m]) == 1
    assert any("Falha ao entrar na fila" in m for m in messages)

    client.responses[SEARCH_STATE] = {"searchState": "Searching"}
    clock["t"] += SEARCH_CHECK_SECONDS
    engine.tick()

    assert any("Fila retomada" in m for m in messages)


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
