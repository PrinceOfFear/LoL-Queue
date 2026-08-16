from lolqueue.config import Config
from lolqueue.core.champ_select import (
    MAX_LOCK_ATTEMPTS,
    ChampSelectController,
    find_current_action,
    local_position,
)
from lolqueue.core.champions import ChampionCatalog
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

SUMMARY = [
    {"id": 64, "name": "Lee Sin", "alias": "LeeSin"},
    {"id": 11, "name": "Master Yi", "alias": "MasterYi"},
]


def session(action_type="pick", completed=False, in_progress=True, actor=0):
    return {
        "localPlayerCellId": 0,
        "actions": [
            [
                {
                    "id": 7,
                    "actorCellId": actor,
                    "championId": 0,
                    "completed": completed,
                    "isInProgress": in_progress,
                    "type": action_type,
                }
            ]
        ],
    }


def ban_session(prior=()):
    """Sessão na vez de banir, após ações já concluídas de outros jogadores.

    `prior` é uma lista de (tipo, championId) — o que já saiu de jogo
    antes da nossa vez.
    """
    concluidas = [
        {
            "id": 100 + indice,
            "actorCellId": 5 + indice,
            "championId": champion_id,
            "completed": True,
            "isInProgress": False,
            "type": tipo,
        }
        for indice, (tipo, champion_id) in enumerate(prior)
    ]
    minha = {
        "id": 7,
        "actorCellId": 0,
        "championId": 0,
        "completed": False,
        "isInProgress": True,
        "type": "ban",
    }
    return {"localPlayerCellId": 0, "actions": [concluidas, [minha]]}


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def settled_session(champion_id, action_id=7, action_type="pick"):
    """Sessão depois que o cliente fechou a nossa ação.

    `champion_id` é o que ficou de fato registrado — que nem sempre é o
    que mandamos.
    """
    return {
        "localPlayerCellId": 0,
        "actions": [
            [
                {
                    "id": action_id,
                    "actorCellId": 0,
                    "championId": champion_id,
                    "completed": True,
                    "isInProgress": False,
                    "type": action_type,
                }
            ]
        ],
    }


def make_controller(config, responses, log=None):
    responses = {endpoints.CHAMPION_SUMMARY: SUMMARY, **responses}
    client = FakeLcuClient(responses=responses)
    catalog = ChampionCatalog(client)
    catalog.load()
    clock = Clock()
    controller = ChampSelectController(client, config, catalog, log=log, now=clock)
    return controller, client, clock


def locks(client):
    """Só os PATCH que tentam travar a ação."""
    return [body for _, body in client.payloads if body.get("completed")]


PICK_CONFIG = Config(auto_pick=True, pick_priority=[64, 11], lock_delay_seconds=3.0)


def test_finds_our_in_progress_action():
    assert find_current_action(session())["id"] == 7


def test_ignores_another_players_action():
    assert find_current_action(session(actor=3)) is None


def test_ignores_completed_action():
    assert find_current_action(session(completed=True)) is None


def test_ignores_action_not_in_progress():
    assert find_current_action(session(in_progress=False)) is None


def test_hovers_the_first_available_pick():
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    path, body = client.payloads[-1]
    assert path == endpoints.CHAMP_SELECT_ACTION.format(action_id=7)
    assert body == {"championId": 64}


def test_falls_through_to_the_next_when_first_is_taken():
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [11],
        },
    )
    controller.tick()
    _, body = client.payloads[-1]
    assert body == {"championId": 11}


def test_does_not_lock_before_the_delay():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 2.0
    controller.tick()
    assert all(body.get("completed") is not True for _, body in client.payloads)


def test_locks_after_the_delay():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert client.payloads[-1][1] == {"championId": 64, "completed": True}


def test_hovers_only_once_while_waiting():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 1.0
    controller.tick()
    clock.value = 2.0
    controller.tick()
    hovers = [b for _, b in client.payloads if b == {"championId": 64}]
    assert len(hovers) == 1


def test_no_available_champion_locks_nothing_and_warns():
    messages = []
    responses = {
        endpoints.CHAMPION_SUMMARY: SUMMARY,
        endpoints.CHAMP_SELECT_SESSION: session(),
        endpoints.PICKABLE_CHAMPIONS: [99],
    }
    client = FakeLcuClient(responses=responses)
    catalog = ChampionCatalog(client)
    catalog.load()
    controller = ChampSelectController(
        client, PICK_CONFIG, catalog, log=messages.append, now=Clock()
    )
    controller.tick()
    assert client.payloads == []
    assert messages


def test_ban_uses_the_ban_list():
    config = Config(auto_ban=True, ban_priority=[11], lock_delay_seconds=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: session(action_type="ban"),
            endpoints.BANNABLE_CHAMPIONS: [11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_works_even_when_the_client_reports_no_bannable_ids():
    """O cliente responde `[-1]` em `bannable-champion-ids`.

    Filtrar por essa lista deixava o banimento sempre vazio: nenhum id
    real casa com o sentinela, então a vez de banir passava em branco.
    Quem pode ser banido sai da própria sessão.
    """
    config = Config(auto_ban=True, ban_priority=[11], lock_delay_seconds=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_skips_a_champion_already_banned():
    config = Config(auto_ban=True, ban_priority=[64, 11], lock_delay_seconds=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", 64)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_skips_a_champion_already_picked():
    """O segundo turno de bans acontece com campeões já escolhidos.

    Banir um deles é recusado pelo cliente.
    """
    config = Config(auto_ban=True, ban_priority=[64, 11], lock_delay_seconds=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("pick", 64)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_a_ban_that_passed_does_not_block_the_champion():
    """Uma vez de banir que expira fica registrada com `championId` -1.

    Isso não tira campeão nenhum de jogo.
    """
    config = Config(auto_ban=True, ban_priority=[64], lock_delay_seconds=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", -1)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 64}


def test_does_not_hover_again_after_locking():
    """A sessão ainda anuncia a ação em andamento logo depois do lock.

    Sem lembrar do que já travou, o tick seguinte refazia o hover — o
    registro mostrava a mesma escolha duas vezes.
    """
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    depois_do_lock = len(client.payloads)
    clock.value = 4.0
    controller.tick()
    assert len(client.payloads) == depois_do_lock


def test_only_reports_the_lock_after_the_client_records_it():
    """O 2xx do PATCH não prova nada.

    Numa ranqueada de verdade o banimento respondeu sem erro, o app
    anunciou "confirmado" e a sessão fechou a ação com -1: ninguém foi
    banido. Quem decide se deu certo é a sessão, não a resposta.
    """
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert not any("confirmado" in m for m in mensagens)

    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(64)
    clock.value = 3.75
    controller.tick()
    assert any("Lee Sin confirmado" in m for m in mensagens)


def test_warns_when_the_client_ignored_the_lock():
    """Vez de banir que passou em branco fica registrada com -1."""
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(-1)
    clock.value = 3.75
    controller.tick()
    assert any("não registrou" in m for m in mensagens)
    assert not any("confirmado" in m for m in mensagens)


def test_reports_the_champion_the_client_actually_recorded():
    """Se fechou com outro campeão, o registro precisa dizer qual."""
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(11)
    clock.value = 3.75
    controller.tick()
    assert any("Master Yi" in m for m in mensagens)


def test_retries_the_lock_while_the_client_ignores_it():
    """Enquanto a ação continuar aberta, insiste.

    O cliente engole a primeira trava quando a fase de ban ainda está
    abrindo. Sem reenviar, a vez passa em branco.
    """
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert len(locks(client)) == 1
    clock.value = 4.6
    controller.tick()
    assert len(locks(client)) == 2


def test_gives_up_after_repeated_lock_attempts():
    """Insistir para sempre viraria enxurrada de PATCH no cliente."""
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    for extra in range(1, MAX_LOCK_ATTEMPTS + 10):
        clock.value = 3.5 + extra * 1.5
        controller.tick()
    assert len(locks(client)) == MAX_LOCK_ATTEMPTS


def test_pick_skips_a_champion_someone_else_already_took():
    """A lista de escolhíveis pode demorar a refletir o pick alheio."""
    config = Config(auto_pick=True, pick_priority=[64, 11], lock_delay_seconds=0.0)
    tomado = ban_session([("pick", 64)])
    tomado["actions"][1][0]["type"] = "pick"
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: tomado,
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def positioned_session(position):
    """Sessão na vez de escolher, com a rota já atribuída."""
    data = session()
    data["myTeam"] = [{"cellId": 0, "assignedPosition": position}]
    return data


def test_reads_the_assigned_position_of_the_local_player():
    assert local_position(positioned_session("utility")) == "utility"


def test_no_position_when_the_mode_does_not_assign_one():
    """Cego e coop não distribuem rota: `assignedPosition` vem vazio."""
    assert local_position(positioned_session("")) == ""
    assert local_position(session()) == ""


def test_picks_from_the_list_of_the_assigned_position():
    """Autofill no suporte precisa usar a lista de suporte."""
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_seconds=0.0,
    )
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("utility"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_picks_from_the_general_list_when_the_position_has_none():
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_seconds=0.0,
    )
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("jungle"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 64}


def test_announces_the_assigned_position_once():
    """O usuário precisa ver de que rota veio a lista usada."""
    mensagens = []
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_seconds=0.0,
    )
    controller, client, clock = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("utility"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 1.0
    controller.tick()
    anuncios = [m for m in mensagens if "Suporte" in m]
    assert len(anuncios) == 1


def test_auto_pick_off_means_no_action_on_pick():
    controller, client, _ = make_controller(
        Config(auto_pick=False, pick_priority=[64]),
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    assert client.payloads == []


def test_reset_clears_hover_state_between_games():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    controller.reset()
    clock.value = 10.0
    controller.tick()
    hovers = [b for _, b in client.payloads if b == {"championId": 64}]
    assert len(hovers) == 2
