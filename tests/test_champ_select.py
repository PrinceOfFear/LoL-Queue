from lolqueue.config import Config
from lolqueue.core.champ_select import ChampSelectController, find_current_action
from lolqueue.core.champions import ChampionCatalog
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

SUMMARY = [{"id": 64, "name": "Lee Sin"}, {"id": 11, "name": "Master Yi"}]


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


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def make_controller(config, responses):
    responses = {endpoints.CHAMPION_SUMMARY: SUMMARY, **responses}
    client = FakeLcuClient(responses=responses)
    catalog = ChampionCatalog(client)
    catalog.load()
    clock = Clock()
    controller = ChampSelectController(client, config, catalog, now=clock)
    return controller, client, clock


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


def test_ban_uses_the_ban_list_and_bannable_ids():
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
