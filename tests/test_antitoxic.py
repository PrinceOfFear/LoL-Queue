"""O silêncio ligado durante a seleção.

Pedido do usuário: mutar chat e emotes de aliados e inimigos antes de a
partida começar. As chaves são as que o cliente do LoL aceita de verdade
em `/lol-game-settings/v1/game-settings`.

Duas delas merecem nota. `Chat.EnableChat` é a que realmente desliga o
chat — o jogador testou a versão que mexia só nas chaves de HUD e
continuou vendo tudo. E ela não aparece na *leitura* do cliente, só na
escrita: o valor anterior tem de vir do `game.cfg`, que aqui entra por
`read_flag`. Emote de aliado não tem chave, e por isso não aparece.
"""

from lolqueue.config import Config
from lolqueue.core.antitoxic import MUTED, SECTION, MuteGuard
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

LIGADO = Config(mute_before_game=True)
DESLIGADO = Config(mute_before_game=False)

#: O que o cliente devolve num jogador que nunca mexeu nisso.
BARULHO = {
    "HUD": {
        "ShowAlliedChat": True,
        "ShowAllChannelChat": True,
        "HideEnemySummonerEmotes": False,
        "ChatChannelVisibility": 2,
        "EmotePopupUIDisplayMode": 0,
        "FlipMiniMap": False,
    }
}

#: O `game.cfg` desse mesmo jogador, para as chaves que o cliente não
#: devolve na leitura.
DISCO = {"EnableChat": True}

#: O silêncio completo, do jeito que sai no PATCH.
SILENCIO = {"Chat": {"EnableChat": False}, SECTION: dict(MUTED[SECTION])}


def make_guard(config=LIGADO, settings=None, failures=None, disco=None):
    client = FakeLcuClient(
        responses={endpoints.GAME_SETTINGS: settings or BARULHO},
        failures=failures,
    )
    lido = DISCO if disco is None else disco
    registro: list[str] = []
    guard = MuteGuard(
        client,
        config,
        log=registro.append,
        read_flag=lambda nome, padrao: lido.get(nome, padrao),
    )
    return guard, client, registro


def patches(client):
    return [body for path, body in client.payloads if path == endpoints.GAME_SETTINGS]


def test_mutes_chat_and_enemy_emotes():
    guard, client, _ = make_guard()
    assert guard.apply() is True
    assert patches(client) == [SILENCIO]


def test_the_silence_turns_the_game_chat_off():
    """A chave mestra, e a razão de a primeira versão não ter funcionado.

    Esconder as janelas do chat deixa o chat ligado: as mensagens
    continuam chegando e o jogador continua lendo. `EnableChat` é o
    interruptor.
    """
    guard, client, _ = make_guard()
    guard.apply()
    assert patches(client)[0]["Chat"] == {"EnableChat": False}


def test_the_chat_window_goes_away_too():
    guard, client, _ = make_guard()
    guard.apply()
    assert patches(client)[0][SECTION]["ChatChannelVisibility"] == 0


def test_the_previous_chat_state_comes_from_the_config_file():
    """O cliente aceita escrever em `Chat`, mas não a devolve na leitura.

    Sem ler o disco, `restore` teria de chutar — e chutar aqui significa
    deixar o jogador sem chat depois da partida.
    """
    guard, client, _ = make_guard()
    guard.apply()
    assert guard.restore() is True
    assert patches(client)[-1]["Chat"] == {"EnableChat": True}


def test_a_player_who_already_plays_muted_keeps_it_that_way():
    """Quem já jogava sem chat não deve ganhar chat no fim da partida."""
    guard, client, _ = make_guard(disco={"EnableChat": False})
    guard.apply()
    assert "Chat" not in patches(client)[0]
    guard.restore()
    assert "Chat" not in patches(client)[-1]


def test_leaves_the_players_own_emote_wheel_alone():
    """`EmotePopupUIDisplayMode` é como o jogador abre o menu dele.

    Mexer nela atrapalharia quem o app deveria proteger.
    """
    guard, client, _ = make_guard()
    guard.apply()
    assert "EmotePopupUIDisplayMode" not in patches(client)[0][SECTION]


def test_does_not_repeat_the_patch_on_every_tick():
    guard, client, _ = make_guard()
    guard.apply()
    guard.apply()
    guard.apply()
    assert len(patches(client)) == 1


def test_stays_out_when_the_setting_is_off():
    guard, client, _ = make_guard(config=DESLIGADO)
    assert guard.apply() is False
    assert client.calls == []


def test_says_nothing_to_do_when_already_silent():
    ja = {"HUD": dict(BARULHO["HUD"], **MUTED[SECTION])}
    guard, client, _ = make_guard(settings=ja, disco={"EnableChat": False})
    assert guard.apply() is False
    assert patches(client) == []


def test_only_sends_what_actually_changes():
    """Chat de todos já desligado não precisa ser desligado de novo."""
    quase = {
        "HUD": dict(BARULHO["HUD"], ShowAllChannelChat=False, ChatChannelVisibility=0)
    }
    guard, client, _ = make_guard(settings=quase, disco={"EnableChat": False})
    guard.apply()
    assert patches(client) == [
        {SECTION: {"ShowAlliedChat": False, "HideEnemySummonerEmotes": True}}
    ]


def test_nothing_is_held_before_the_silence():
    """Antes de mutar, a cópia das configurações escreve à vontade."""
    guard, _, _ = make_guard()

    assert guard.forced() == {}


def test_the_silence_holds_every_key_it_stands_on():
    """Quem escreve depois na mesma rota pergunta o que não pode mexer.

    A cópia da conta principal usa `GAME_SETTINGS` e manda o bloco
    inteiro, com o chat ligado. Chegando depois, ela devolvia o chat
    aliado e os emotes do inimigo, e o `_applied` daqui impedia o
    silêncio de voltar: o jogo ficava meio mudo pelo resto da partida.
    """
    guard, _, _ = make_guard()
    guard.apply()

    assert guard.forced() == {secao: dict(v) for secao, v in MUTED.items()}


def test_a_player_who_was_already_silent_is_held_too():
    """O caso que `_original` não cobria: nada mudou, e mesmo assim o
    jogo está mudo — e é dele o pedido de silêncio, não nosso."""
    ja = {"HUD": dict(BARULHO["HUD"], **MUTED[SECTION])}
    guard, _, _ = make_guard(settings=ja, disco={"EnableChat": False})
    guard.apply()

    assert guard.forced() == {secao: dict(v) for secao, v in MUTED.items()}


def test_the_hold_lasts_longer_than_the_selection():
    """`reset` acaba com a seleção; o chat só incomoda depois dela."""
    guard, _, _ = make_guard()
    guard.apply()
    guard.reset()

    assert guard.forced()


def test_giving_the_settings_back_ends_the_hold():
    guard, _, _ = make_guard()
    guard.apply()
    guard.restore()

    assert guard.forced() == {}


def test_gives_back_exactly_what_the_player_had():
    quase = {
        "HUD": dict(BARULHO["HUD"], ShowAllChannelChat=False, ChatChannelVisibility=0)
    }
    guard, client, _ = make_guard(settings=quase, disco={"EnableChat": False})
    guard.apply()
    assert guard.restore() is True
    assert patches(client)[-1] == {
        SECTION: {"ShowAlliedChat": True, "HideEnemySummonerEmotes": False}
    }


def test_restoring_without_having_muted_does_nothing():
    guard, client, _ = make_guard()
    assert guard.restore() is False
    assert client.payloads == []


def test_restoring_twice_does_not_write_again():
    guard, client, _ = make_guard()
    guard.apply()
    guard.restore()
    assert guard.restore() is False
    assert len(patches(client)) == 2


def test_a_new_selection_may_mute_again():
    guard, client, _ = make_guard()
    guard.apply()
    guard.reset()
    guard.apply()
    assert len(patches(client)) == 2


def test_reset_does_not_touch_the_settings():
    guard, client, _ = make_guard()
    guard.apply()
    guard.reset()
    assert len(patches(client)) == 1


def test_a_refusal_from_the_client_is_not_fatal():
    guard, client, _ = make_guard(failures={("PATCH", endpoints.GAME_SETTINGS)})
    assert guard.apply() is False


def test_an_unreadable_client_is_not_fatal():
    guard, client, _ = make_guard(failures={endpoints.GAME_SETTINGS})
    assert guard.apply() is False
    assert patches(client) == []


def test_a_client_without_the_hud_section_is_not_fatal():
    guard, client, _ = make_guard(settings={"General": {}})
    assert guard.apply() is False


def test_it_reports_what_it_did():
    guard, _, registro = make_guard()
    guard.apply()
    guard.restore()
    assert any("Silêncio ligado" in linha for linha in registro)
    assert any("EnableChat" in linha for linha in registro)
    assert any("voltaram ao normal" in linha for linha in registro)


def test_the_setting_comes_on_by_default():
    """Foi o pedido: o app já entra mudo, sem ter de ligar nada."""
    assert Config().mute_before_game is True


# ---------------------------------------------------------------------
# Onde o guarda é acionado: a seleção liga, o fim da partida devolve.
# ---------------------------------------------------------------------


class GuardaFalso:
    def __init__(self):
        self.applied = 0
        self.restored = 0
        self.resets = 0

    def apply(self) -> bool:
        self.applied += 1
        return True

    def restore(self) -> bool:
        self.restored += 1
        return True

    def reset(self) -> None:
        self.resets += 1


def test_the_selection_turns_the_silence_on():
    from tests.test_champ_select import PICK_CONFIG, make_controller

    guarda = GuardaFalso()
    controller, _, _ = make_controller(
        PICK_CONFIG,
        {endpoints.CHAMP_SELECT_SESSION: {"localPlayerCellId": 0, "actions": []}},
        antitoxic=guarda,
    )
    controller.tick()
    assert guarda.applied == 1


def test_a_new_selection_rearms_the_guard():
    from tests.test_champ_select import PICK_CONFIG, make_controller

    guarda = GuardaFalso()
    controller, _, _ = make_controller(
        PICK_CONFIG,
        {endpoints.CHAMP_SELECT_SESSION: {"localPlayerCellId": 0, "actions": []}},
        antitoxic=guarda,
    )
    controller.reset()
    assert (guarda.resets, guarda.restored) == (1, 0)


def test_the_end_of_the_match_gives_the_settings_back():
    from lolqueue.core.engine import Engine
    from lolqueue.core.phases import GameflowPhase

    guarda = GuardaFalso()
    engine = Engine(FakeLcuClient(), Config())
    engine.set_antitoxic(guarda)
    engine.handle_phase(GameflowPhase.CHAMP_SELECT)
    assert guarda.restored == 0
    engine.handle_phase(GameflowPhase.IN_PROGRESS)
    assert guarda.restored == 0
    engine.handle_phase(GameflowPhase.END_OF_GAME)
    assert guarda.restored == 1


def test_turning_the_engine_off_gives_the_settings_back():
    from lolqueue.core.engine import Engine

    guarda = GuardaFalso()
    engine = Engine(FakeLcuClient(), Config())
    engine.set_antitoxic(guarda)
    engine.set_enabled(True)
    assert guarda.restored == 0
    engine.set_enabled(False)
    assert guarda.restored == 1


def test_unchecking_the_setting_gives_the_settings_back():
    """Desmarcar no meio da seleção não espera o fim da partida."""
    config = Config(mute_before_game=True)
    guard, client, _ = make_guard(config=config)
    guard.apply()
    config.mute_before_game = False
    assert guard.apply() is False
    assert patches(client)[-1] == {
        "Chat": {"EnableChat": True},
        SECTION: {
            "ShowAlliedChat": True,
            "ShowAllChannelChat": True,
            "HideEnemySummonerEmotes": False,
            "ChatChannelVisibility": 2,
        },
    }
