import pytest

from lolqueue.config import Config
from lolqueue.core.engine import (
    MAX_FAILURES,
    POSTGAME_GRACE_SECONDS,
    QUEUE_RETRY_SECONDS,
    SEARCH_CHECK_SECONDS,
    Engine,
)
from lolqueue.core.phases import GameflowPhase
from lolqueue.lcu import endpoints
from lolqueue.lcu.client import ClientClosed
from tests.fakes import FakeLcuClient


def sem_atraso(**kwargs):
    """Config que aceita na hora.

    A maioria dos testes daqui é sobre outra coisa — retentativa,
    backoff, fila parada — e não teria por que ficar avançando relógio.
    """
    kwargs.setdefault("accept_delay_min", 0.0)
    kwargs.setdefault("accept_delay_max", 0.0)
    return Config(**kwargs)


class Relogio:
    """Relógio de mentira: só anda quando o teste manda."""

    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora

    def avanca(self, segundos):
        self.agora += segundos


class RastreadorPdl:
    def __init__(self):
        self.phases = []
        self.ticks = 0

    def handle_phase(self, phase):
        self.phases.append(phase)

    def tick(self):
        self.ticks += 1


def make_engine(
    config=None, responses=None, failures=None, closed=False, now=None, rng=None
):
    client = FakeLcuClient(responses=responses, failures=failures, closed=closed)
    extra = {}
    if now is not None:
        extra["now"] = now
    if rng is not None:
        extra["rng"] = rng
    engine = Engine(client, config or sem_atraso(), **extra)
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


def test_lp_tracker_keeps_working_when_queue_automation_is_disabled():
    engine, _client = make_engine()
    tracker = RastreadorPdl()
    engine.set_lp_tracker(tracker)
    engine.set_enabled(False)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.tick()

    assert tracker.phases == [GameflowPhase.END_OF_GAME]
    assert tracker.ticks == 1


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
    engine = Engine(client, sem_atraso(), log=messages.append)
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


def test_champ_select_resets_even_with_the_engine_disabled():
    """O controlador sobrevive a reconexões, não a seleções.

    Se o motor está desligado quando uma seleção nova começa e o
    usuário religa a automação no meio dela, sem isto o controlador
    entraria com trava e prévia de campeão da seleção anterior — a
    fase muda, mas ninguém chama `reset()`.
    """
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
    engine.set_enabled(False)
    engine.handle_phase(GameflowPhase.CHAMP_SELECT)
    assert spy.reset_calls == 1


def test_champ_select_without_controller_does_not_crash():
    engine, _ = make_engine()
    engine.handle_phase(GameflowPhase.CHAMP_SELECT)


# ---------- quando a sala é de outra pessoa ----------
#
# Entrar na sala de um amigo é o caso em que a fila automática atrapalha
# em vez de ajudar: quem manda na busca é o dono, e o app acaba criando
# uma sala paralela e entrando na fila sozinho. Aceitar, banir e
# escolher continuam valendo — é justamente o que o jogador quer que
# siga automático enquanto o amigo conduz.

GUEST_LOBBY = {
    endpoints.LOBBY: {"canStartActivity": False, "localMember": {"isLeader": False}}
}
HOST_LOBBY = {
    endpoints.LOBBY: {"canStartActivity": True, "localMember": {"isLeader": True}}
}


def test_it_does_not_start_the_queue_in_someone_elses_lobby():
    engine, client = make_engine(Config(auto_queue=True), responses=GUEST_LOBBY)

    engine.handle_phase(GameflowPhase.LOBBY)

    assert endpoints.MATCHMAKING_SEARCH not in client.paths("POST")


def test_it_still_accepts_the_match_in_someone_elses_lobby():
    engine, client = make_engine(
        sem_atraso(auto_queue=True, auto_accept=True), responses=GUEST_LOBBY
    )

    engine.handle_phase(GameflowPhase.LOBBY)
    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert endpoints.READY_CHECK_ACCEPT in client.paths("POST")


def test_it_does_not_open_a_lobby_of_its_own_after_being_a_guest():
    """O caso chato: a partida acaba e o app cria sala e fila sozinho."""
    engine, client = make_engine(Config(auto_queue=True), responses=GUEST_LOBBY)

    engine.handle_phase(GameflowPhase.LOBBY)
    engine.handle_phase(GameflowPhase.NONE)

    assert endpoints.LOBBY not in client.paths("POST")


def test_it_opens_its_own_lobby_again_once_it_hosts():
    engine, client = make_engine(Config(auto_queue=True), responses=GUEST_LOBBY)
    engine.handle_phase(GameflowPhase.LOBBY)

    client.responses.update(HOST_LOBBY)
    engine.handle_phase(GameflowPhase.LOBBY)
    engine.handle_phase(GameflowPhase.NONE)

    assert endpoints.LOBBY in client.paths("POST")


def test_turning_the_engine_on_forgets_it_was_a_guest():
    """Ligar o motor é o jogador dizendo o que quer agora."""
    engine, client = make_engine(Config(auto_queue=True), responses=GUEST_LOBBY)
    engine.handle_phase(GameflowPhase.LOBBY)

    engine.set_enabled(True)
    engine.handle_phase(GameflowPhase.NONE)

    assert endpoints.LOBBY in client.paths("POST")


def test_the_option_off_keeps_the_old_behaviour():
    engine, client = make_engine(
        Config(auto_queue=True, queue_only_as_host=False), responses=GUEST_LOBBY
    )

    engine.handle_phase(GameflowPhase.LOBBY)
    engine.handle_phase(GameflowPhase.NONE)

    assert endpoints.LOBBY in client.paths("POST")


def test_it_says_why_it_is_holding_back():
    messages = []
    client = FakeLcuClient(responses=GUEST_LOBBY)
    engine = Engine(client, Config(auto_queue=True), log=messages.append)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.LOBBY)

    assert any("dono da sala" in message for message in messages)


def test_it_does_not_repeat_the_warning_every_tick():
    messages = []
    client = FakeLcuClient(responses=GUEST_LOBBY)
    engine = Engine(client, Config(auto_queue=True), log=messages.append)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.LOBBY)
    engine.tick()
    engine.tick()

    assert len([m for m in messages if "dono da sala" in m]) == 1


def test_a_lobby_without_the_leader_flag_is_treated_as_our_own():
    """Formato inesperado não pode trancar quem está jogando sozinho."""
    engine, client = make_engine(
        Config(auto_queue=True), responses={endpoints.LOBBY: {}}
    )

    engine.handle_phase(GameflowPhase.LOBBY)

    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


# ---------- o atraso antes de aceitar ----------


def test_the_match_is_not_accepted_the_instant_it_is_found():
    """O ponto do atraso: existir uma janela para o usuário desistir."""
    relogio = Relogio()
    engine, client = make_engine(Config(), now=relogio, rng=lambda a, b: 3.0)

    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert client.paths("POST") == []


def test_the_match_is_accepted_once_the_delay_runs_out():
    relogio = Relogio()
    engine, client = make_engine(Config(), now=relogio, rng=lambda a, b: 3.0)

    engine.handle_phase(GameflowPhase.READY_CHECK)
    relogio.avanca(2.9)
    engine.tick()
    assert client.paths("POST") == []

    relogio.avanca(0.2)
    engine.tick()
    assert endpoints.READY_CHECK_ACCEPT in client.paths("POST")


def test_the_draw_uses_the_configured_range():
    pedidos = []
    relogio = Relogio()
    engine, _ = make_engine(
        Config(accept_delay_min=1.5, accept_delay_max=4.5),
        now=relogio,
        rng=lambda low, high: pedidos.append((low, high)) or low,
    )

    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert pedidos == [(1.5, 4.5)]


def test_the_wait_is_announced_so_it_does_not_look_frozen():
    messages = []
    relogio = Relogio()
    client = FakeLcuClient()
    engine = Engine(
        client, Config(), log=messages.append, now=relogio, rng=lambda a, b: 3.0
    )
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert any("3" in m for m in messages), messages


def test_the_delay_is_drawn_again_for_the_next_match():
    """Uma partida recusada não pode deixar o relógio da próxima vencido."""
    pedidos = []
    relogio = Relogio()
    engine, client = make_engine(
        Config(),
        now=relogio,
        rng=lambda low, high: pedidos.append((low, high)) or 3.0,
    )

    engine.handle_phase(GameflowPhase.READY_CHECK)
    relogio.avanca(10.0)
    engine.tick()
    engine.handle_phase(GameflowPhase.NONE)
    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert len(pedidos) == 2
    assert len(client.paths("POST")) == 1, "a segunda não podia sair na hora"


def test_only_one_accept_goes_out_however_many_ticks_pass():
    relogio = Relogio()
    engine, client = make_engine(Config(), now=relogio, rng=lambda a, b: 1.0)

    engine.handle_phase(GameflowPhase.READY_CHECK)
    for _ in range(10):
        relogio.avanca(1.0)
        engine.tick()

    assert len(client.paths("POST")) == 1


def test_a_zero_range_still_accepts_immediately():
    """Quem não quer atraso nenhum continua sendo atendido na hora."""
    engine, client = make_engine(sem_atraso())

    engine.handle_phase(GameflowPhase.READY_CHECK)

    assert endpoints.READY_CHECK_ACCEPT in client.paths("POST")


def test_the_delay_does_not_leak_into_other_phases():
    """Só o "aceitar" espera; entrar na fila continua imediato."""
    relogio = Relogio()
    engine, client = make_engine(
        sem_atraso(auto_queue=True),
        responses=LOBBY_READY,
        now=relogio,
        rng=lambda a, b: 5.0,
    )

    engine.handle_phase(GameflowPhase.LOBBY)

    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


# ---------- a espera depois da partida ----------
#
# O cliente do LoL leva alguns segundos para soltar a partida anterior e
# recusa a fila com 400/ALREADY_IN_GAME até lá. Antes disto o app
# torrava as três tentativas em dois segundos e desistia.


def fila_apos_partida(**kwargs):
    kwargs.setdefault("auto_queue", True)
    kwargs.setdefault("postgame_delay_min", 8.0)
    kwargs.setdefault("postgame_delay_max", 8.0)
    return sem_atraso(**kwargs)


def buscas(client):
    return [p for p in client.paths("POST") if p == endpoints.MATCHMAKING_SEARCH]


def test_the_queue_waits_for_the_client_to_settle_after_a_match():
    relogio = Relogio()
    engine, client = make_engine(
        fila_apos_partida(), responses=LOBBY_READY, now=relogio
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)

    assert buscas(client) == [], "buscou antes de o cliente assentar"

    relogio.avanca(8.1)
    engine.tick()
    assert buscas(client), "não buscou depois da espera"


def test_the_wait_is_drawn_from_the_configured_range():
    pedidos = []
    relogio = Relogio()
    engine, _ = make_engine(
        fila_apos_partida(postgame_delay_min=6.0, postgame_delay_max=10.0),
        responses=LOBBY_READY,
        now=relogio,
        rng=lambda low, high: pedidos.append((low, high)) or 7.0,
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)

    assert pedidos == [(6.0, 10.0)]


def test_the_wait_is_announced_once():
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(responses=LOBBY_READY)
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    for _ in range(10):
        relogio.avanca(0.2)
        engine.tick()

    esperas = [m for m in messages if "entrando na fila em" in m.casefold()]
    assert len(esperas) == 1, messages


def test_a_lobby_with_no_match_before_it_does_not_wait():
    """Ligar o motor no lobby não é volta de partida — entra na hora."""
    engine, client = make_engine(fila_apos_partida(), responses=LOBBY_READY)

    engine.handle_phase(GameflowPhase.LOBBY)

    assert buscas(client)


def test_a_refusal_right_after_the_match_does_not_burn_the_retries():
    """400/ALREADY_IN_GAME é "ainda não", não falha que gasta chance."""
    relogio = Relogio()
    engine, client = make_engine(
        fila_apos_partida(),
        responses=LOBBY_READY,
        failures={endpoints.MATCHMAKING_SEARCH},
        now=relogio,
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    for _ in range(60):  # 12 segundos de ticks
        relogio.avanca(0.2)
        engine.tick()

    insistiu = len(buscas(client))
    assert insistiu > MAX_FAILURES, f"desistiu como antes: {insistiu} tentativas"

    # e assim que o cliente aceita, a fila entra de verdade
    client.failures.clear()
    relogio.avanca(QUEUE_RETRY_SECONDS + 0.1)
    engine.tick()
    assert len(buscas(client)) == insistiu + 1


def test_the_retries_after_a_match_are_spaced_out():
    """Marteladas de 200ms viram enxurrada de erro no registro."""
    relogio = Relogio()
    engine, client = make_engine(
        fila_apos_partida(),
        responses=LOBBY_READY,
        failures={endpoints.MATCHMAKING_SEARCH},
        now=relogio,
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    for _ in range(50):  # 10 segundos de ticks
        relogio.avanca(0.2)
        engine.tick()

    assert len(buscas(client)) <= 10 / QUEUE_RETRY_SECONDS + 1


def test_the_settling_client_is_reported_once_not_every_tick():
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(
        responses=LOBBY_READY, failures={endpoints.MATCHMAKING_SEARCH}
    )
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    for _ in range(50):
        relogio.avanca(0.2)
        engine.tick()

    falhas = [m for m in messages if "Falha em" in m]
    assert falhas == [], falhas
    encerrando = [m for m in messages if "encerrando a partida" in m]
    assert len(encerrando) == 1, messages


def test_a_failure_far_from_any_match_still_gives_up():
    """Fora da janela pós-partida nada muda: erro é erro."""
    relogio = Relogio()
    engine, client = make_engine(
        fila_apos_partida(),
        responses=LOBBY_READY,
        failures={endpoints.MATCHMAKING_SEARCH},
        now=relogio,
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(POSTGAME_GRACE_SECONDS + 1.0)
    for _ in range(30):
        relogio.avanca(0.2)
        engine.tick()

    assert len(buscas(client)) == MAX_FAILURES


def test_the_wait_does_not_carry_over_to_the_next_lobby():
    """Entrou na fila uma vez, a espera daquela partida morreu ali."""
    relogio = Relogio()
    engine, client = make_engine(
        fila_apos_partida(), responses=LOBBY_READY, now=relogio
    )

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    engine.tick()
    assert len(buscas(client)) == 1

    engine.handle_phase(GameflowPhase.MATCHMAKING)
    engine.handle_phase(GameflowPhase.LOBBY)
    engine.tick()
    assert len(buscas(client)) == 2, "esperou de novo sem partida no meio"


def test_getting_into_the_queue_is_always_announced_after_a_wait():
    """Quem viu "entrando em 7s" precisa ver o desfecho.

    A retomada da busca entra calada de propósito, para não repetir a
    mesma linha a cada poucos segundos. Mas depois de uma espera
    anunciada, o silêncio vira dúvida: entrou ou travou?
    """
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(
        responses=LOBBY_READY, failures={endpoints.MATCHMAKING_SEARCH}
    )
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    for _ in range(20):
        relogio.avanca(0.2)
        engine.tick()

    client.failures.clear()
    relogio.avanca(QUEUE_RETRY_SECONDS + 0.1)
    engine.tick()

    assert any("Entrando na fila" in m for m in messages), messages


def test_a_stalled_search_right_after_the_match_is_not_reported_as_a_problem():
    """No pós-jogo a busca "parada" é o cliente encerrando, não anomalia."""
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(
        responses={
            **LOBBY_READY,
            SEARCH_STATE: {"searchState": "Error", "errors": []},
        },
        failures={endpoints.MATCHMAKING_SEARCH},
    )
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    for _ in range(30):
        relogio.avanca(0.2)
        engine.tick()

    assert not any("Busca parada" in m for m in messages), messages


def test_far_from_a_match_a_stalled_search_is_still_reported():
    """Fora do pós-jogo a busca parada é anomalia de verdade e tem de aparecer."""
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(
        responses={
            **LOBBY_READY,
            SEARCH_STATE: {"searchState": "Error", "errors": []},
        }
    )
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(SEARCH_CHECK_SECONDS + 0.1)
    engine.tick()

    assert any("Busca parada" in m for m in messages), messages


def test_there_is_no_recovery_notice_for_a_problem_never_announced():
    """"Fila retomada" sem "Busca parada" antes é resposta sem pergunta."""
    messages = []
    relogio = Relogio()
    client = FakeLcuClient(
        responses={
            **LOBBY_READY,
            SEARCH_STATE: {"searchState": "Error", "errors": []},
        }
    )
    engine = Engine(client, fila_apos_partida(), log=messages.append, now=relogio)
    engine.set_enabled(True)

    engine.handle_phase(GameflowPhase.END_OF_GAME)
    engine.handle_phase(GameflowPhase.LOBBY)
    relogio.avanca(8.1)
    engine.tick()
    client.responses[SEARCH_STATE] = {"searchState": "Searching", "errors": []}
    relogio.avanca(SEARCH_CHECK_SECONDS + 0.1)
    engine.tick()

    assert not any("Fila retomada" in m for m in messages), messages


# ---------- a cópia das configurações do jogo ----------


class CopiaFalsa:
    def __init__(self):
        self.chegadas = []
        self.voltas = 0

    def account_arrived(self, identity):
        self.chegadas.append(identity)

    def tick(self):
        self.voltas += 1


def com_copia():
    copia = CopiaFalsa()
    engine = Engine(FakeLcuClient(), Config())
    engine.set_game_sync(copia)
    return engine, copia


def test_the_game_settings_copy_does_not_need_the_queue_engine_on():
    """Copiar teclas não é fila automática e não pode depender dela."""
    engine, copia = com_copia()
    engine.set_enabled(False)
    engine.tick()
    assert copia.voltas == 1


def test_the_engine_passes_on_who_logged_in():
    engine, copia = com_copia()
    engine.handle_identity("alguem")
    assert copia.chegadas == ["alguem"]


def test_an_engine_without_the_copy_still_turns():
    """A cópia é opcional: sem ela o motor não pode quebrar."""
    engine = Engine(FakeLcuClient(), Config())
    engine.handle_identity("alguem")
    engine.tick()

# ---------- rotas pedidas na fila ----------


def lobby_com(primeira=None, segunda=None):
    return {
        endpoints.LOBBY: {
            "canStartActivity": True,
            "localMember": {
                "isLeader": True,
                "firstPositionPreference": primeira,
                "secondPositionPreference": segunda,
            },
        }
    }


def test_it_asks_for_the_chosen_positions_before_queueing():
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="jungle", secondary_position="top"),
        responses=lobby_com(),
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert (
        endpoints.LOBBY_POSITION_PREFERENCES,
        {"firstPreference": "JUNGLE", "secondPreference": "TOP"},
    ) in client.payloads


def test_a_single_choice_leaves_the_second_slot_empty():
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="middle"), responses=lobby_com()
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert (
        endpoints.LOBBY_POSITION_PREFERENCES,
        {"firstPreference": "MIDDLE", "secondPreference": "UNSELECTED"},
    ) in client.payloads


def test_it_says_nothing_when_the_client_already_has_them():
    """Sem isto o app mandaria um PUT a cada entrada na fila."""
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="jungle", secondary_position="top"),
        responses=lobby_com("JUNGLE", "TOP"),
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.LOBBY_POSITION_PREFERENCES not in client.paths("PUT")


def test_no_choice_means_the_client_keeps_what_it_had():
    engine, client = make_engine(Config(auto_queue=True), responses=lobby_com())
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.LOBBY_POSITION_PREFERENCES not in client.paths("PUT")


def test_a_queue_without_positions_is_left_alone():
    """ARAM não tem onde guardar rota — pedir seria erro garantido."""
    engine, client = make_engine(
        Config(auto_queue=True, queue_id=450, primary_position="jungle"),
        responses=lobby_com(),
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.LOBBY_POSITION_PREFERENCES not in client.paths("PUT")


def test_a_refused_request_does_not_cost_the_queue():
    """A rota não é confirmada pela sonda: falhar nela não pode trancar a fila."""
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="jungle"),
        responses=lobby_com(),
        failures=[endpoints.LOBBY_POSITION_PREFERENCES],
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.MATCHMAKING_SEARCH in client.paths("POST")


def test_a_refused_request_is_not_repeated_forever():
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="jungle"),
        responses=lobby_com(),
        failures=[endpoints.LOBBY_POSITION_PREFERENCES],
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    engine.handle_phase(GameflowPhase.NONE)
    engine.handle_phase(GameflowPhase.LOBBY)
    assert client.paths("PUT").count(endpoints.LOBBY_POSITION_PREFERENCES) == 1


def test_a_guest_does_not_touch_the_positions():
    """Na sala de outro o app não mexe em nada da fila."""
    responses = lobby_com()
    responses[endpoints.LOBBY]["localMember"]["isLeader"] = False
    engine, client = make_engine(
        Config(auto_queue=True, primary_position="jungle", queue_only_as_host=True),
        responses=responses,
    )
    engine.handle_phase(GameflowPhase.LOBBY)
    assert endpoints.LOBBY_POSITION_PREFERENCES not in client.paths("PUT")


class _LivePdlTracker(RastreadorPdl):
    def __init__(self):
        super().__init__()
        self.started = 0
        self.stopped = 0

    def start_live_events(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def test_engine_keeps_the_live_pdl_subscription_with_its_connection():
    engine, _client = make_engine()
    tracker = _LivePdlTracker()

    engine.set_lp_tracker(tracker)
    engine.close()

    assert tracker.started == 1
    assert tracker.stopped == 1
