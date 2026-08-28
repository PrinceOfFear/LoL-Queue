"""O retrato que aparece no cliente do LoL antes da sua vez.

Pedido do usuário: ver o boneco que vai ser escolhido dentro do jogo, e
não só na tela do app. É a mesma declaração de intenção de quando se
clica num campeão durante os banimentos — mostra, mas não trava.
"""

from lolqueue.config import PICK_INTENT_CEILING, Config
from lolqueue.core.champ_select import find_pick_action
from lolqueue.lcu import endpoints

from tests.test_champ_select import PICK_CONFIG, make_controller

BAN_TURN = {
    "localPlayerCellId": 0,
    "actions": [
        [
            {
                "id": 3,
                "actorCellId": 0,
                "championId": 0,
                "completed": False,
                "isInProgress": True,
                "type": "ban",
            }
        ],
        [
            {
                "id": 7,
                "actorCellId": 0,
                "championId": 0,
                "completed": False,
                "isInProgress": False,
                "type": "pick",
            }
        ],
    ],
}


def intents(client):
    """Só os PATCH que mostram sem travar."""
    return [
        (path, body)
        for path, body in client.payloads
        if "championId" in body and not body.get("completed")
    ]


def controller_on_ban_turn(config=PICK_CONFIG, session=None):
    seen: list = []
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: session or BAN_TURN,
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
            endpoints.BANNABLE_CHAMPIONS: [],
        },
        on_pick_predicted=seen.append,
    )
    return controller, client


def test_finds_the_pick_action_before_its_turn():
    assert find_pick_action(BAN_TURN)["id"] == 7


def test_ignores_another_players_pick_action():
    outro = {
        "localPlayerCellId": 0,
        "actions": [[dict(BAN_TURN["actions"][1][0], actorCellId=4)]],
    }
    assert find_pick_action(outro) is None


def test_ignores_a_pick_already_locked():
    fechada = {
        "localPlayerCellId": 0,
        "actions": [[dict(BAN_TURN["actions"][1][0], completed=True)]],
    }
    assert find_pick_action(fechada) is None


def test_shows_the_predicted_champion_in_the_client():
    controller, client = controller_on_ban_turn()
    controller.tick()
    assert (endpoints.CHAMP_SELECT_ACTION.format(action_id=7), {"championId": 64}) in (
        intents(client)
    )


def test_does_not_lock_while_only_showing():
    controller, client = controller_on_ban_turn()
    controller.tick()
    assert [body for _, body in client.payloads if body.get("completed")] == []


def test_does_not_repeat_the_same_intent():
    controller, client = controller_on_ban_turn()
    controller.tick()
    controller.tick()
    controller.tick()
    assert len(intents(client)) == 1


def test_skips_when_the_client_already_shows_it():
    ja = {
        "localPlayerCellId": 0,
        "actions": [
            BAN_TURN["actions"][0],
            [dict(BAN_TURN["actions"][1][0], championId=64)],
        ],
    }
    controller, client = controller_on_ban_turn(session=ja)
    controller.tick()
    assert intents(client) == []


def test_respects_the_setting_being_off():
    config = Config(
        auto_pick=True,
        pick_priority=[64, 11],
        show_pick_intent=False,
        lock_delay_min=3.0,
        lock_delay_max=3.0,
    )
    controller, client = controller_on_ban_turn(config=config)
    controller.tick()
    assert intents(client) == []


def test_stays_out_of_the_way_once_the_turn_arrives():
    """Chegada a vez, quem patcha é o par hover/trava, com o atraso dele."""
    from tests.test_champ_select import session

    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=[].append,
    )
    controller.tick()
    # Um único PATCH — o hover. A intenção não entra em cima dele, senão
    # o relógio do atraso configurado seria reiniciado a cada tick.
    assert len(intents(client)) == 1
    clock.value += 3.0
    controller.tick()
    assert [body for _, body in client.payloads if body.get("completed")] == [
        {"championId": 64, "completed": True}
    ]


def test_the_setting_comes_on_by_default():
    """Foi o pedido: ver o boneco no jogo sem ter de ligar nada."""
    assert Config().show_pick_intent is True


# ---------------------------------------------------------------------
# A espera antes de mostrar.
#
# Queixa do usuário: o retrato aparecia para o time antes de o cliente
# terminar de carregar a seleção — cedo demais, e sobra partida inteira
# para alguém encher o saco por causa do pick.
# ---------------------------------------------------------------------

ATRASO = Config(
    auto_pick=True,
    pick_priority=[64, 11],
    lock_delay_min=3.0,
    lock_delay_max=3.0,
    pick_intent_delay=8.0,
)


def controller_com_atraso():
    controller, client, clock = make_controller(
        ATRASO,
        {
            endpoints.CHAMP_SELECT_SESSION: BAN_TURN,
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
            endpoints.BANNABLE_CHAMPIONS: [],
        },
        on_pick_predicted=[].append,
    )
    return controller, client, clock


def test_does_not_declare_the_intent_as_soon_as_the_session_opens():
    controller, client, _ = controller_com_atraso()
    controller.tick()
    assert intents(client) == []


def test_declares_the_intent_once_the_wait_is_over():
    controller, client, clock = controller_com_atraso()
    controller.tick()
    clock.value += 8.0
    controller.tick()
    assert intents(client) == [
        (endpoints.CHAMP_SELECT_ACTION.format(action_id=7), {"championId": 64})
    ]


def test_the_wait_starts_over_on_the_next_selection():
    """Cada seleção conta o seu próprio tempo, não o da anterior."""
    controller, client, clock = controller_com_atraso()
    clock.value += 30.0
    controller.reset()
    controller.tick()
    assert intents(client) == []
    clock.value += 8.0
    controller.tick()
    assert len(intents(client)) == 1


def test_the_wait_is_configurable_and_defaults_to_a_visible_pause():
    assert Config().pick_intent_delay == 8.0
    assert Config(pick_intent_delay=1000).pick_intent_delay == PICK_INTENT_CEILING
