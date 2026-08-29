"""As configurações de dentro do jogo, copiadas da conta principal.

O que está em jogo aqui não é conforto: teclas trocadas de lugar perdem
a partida de quem entra na conta de outra pessoa. E copiar demais é tão
ruim quanto copiar de menos — a qualidade gráfica e o modo de vídeo são
do computador, e o modo de vídeo é justamente o que a captura do
minimapa lê.
"""

from __future__ import annotations

import pytest

from lolqueue.config import Config
from lolqueue.core.accounts import Accounts, account_key
from lolqueue.core.gamesettings import (
    APPLY_DELAYS,
    GameSettingsSync,
    apply,
    capture,
    strip_machine,
)
from lolqueue.core.identity import Identity
from lolqueue.lcu.client import LcuError
from lolqueue.lcu.endpoints import GAME_SETTINGS, INPUT_SETTINGS

JOGO = {
    "General": {"WindowMode": 2, "CursorScale": 1.4, "PredictMovement": True},
    "HUD": {"FlipMiniMap": False, "MinimapScale": 0.8},
    "Performance": {"ShadowsEnabled": True},
}
TECLAS = {
    "GameEvents": {"evtCastSpell1": "[q]", "evtCastAvatarSpell1": "[d]"},
    "Quickbinds": {"evtCastSpell1smart": True},
}


def quem(nome: str = "Thiago", tag: str = "BR1") -> Identity:
    return Identity(game_name=nome, tag_line=tag, region="BR", level=300)


class ClienteFalso:
    """Um cliente do LoL que responde de memória e anota o que escrevem."""

    def __init__(self, jogo=None, teclas=None, erro: str = "") -> None:
        self.jogo = JOGO if jogo is None else jogo
        self.teclas = TECLAS if teclas is None else teclas
        self.erro = erro
        self.escrito: list[tuple[str, dict]] = []

    def get(self, path: str):
        if self.erro:
            raise LcuError(self.erro)
        return self.jogo if path == GAME_SETTINGS else self.teclas

    def patch(self, path: str, json=None):
        if self.erro:
            raise LcuError(self.erro)
        self.escrito.append((path, json))
        return None


def relogio(marcas: list[float]):
    """Um relógio que só anda quando o teste manda."""
    estado = {"agora": marcas[0]}

    def ler() -> float:
        return estado["agora"]

    return ler, estado


def com_modelo(now=None):
    """Duas contas: a principal com fotografia, e a que vai recebê-la."""
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    contas.arrive(quem("Amigo", "BR2"), Config())
    contas.set_game_settings(contas.main, {"game": JOGO, "input": TECLAS})
    return contas


# --- a fotografia -------------------------------------------------------


def test_the_snapshot_leaves_the_machine_settings_behind():
    """Qualidade gráfica e modo de vídeo são do PC, não de quem joga."""
    tirada = capture(ClienteFalso())

    assert "Performance" not in tirada["game"]
    assert "WindowMode" not in tirada["game"]["General"]
    assert tirada["game"]["General"]["CursorScale"] == 1.4
    assert tirada["game"]["HUD"]["MinimapScale"] == 0.8
    assert tirada["input"] == TECLAS


def test_the_keys_are_copied_whole():
    """Tecla é tudo ou nada: meia cópia é pior do que nenhuma."""
    assert strip_machine({"GameEvents": {"evtCastSpell1": "[q]"}}) == {
        "GameEvents": {"evtCastSpell1": "[q]"}
    }


def test_applying_writes_the_two_halves():
    cliente = ClienteFalso()
    escrito = apply(cliente, {"game": {"HUD": {"MinimapScale": 0.8}}, "input": TECLAS})

    assert escrito == ["interface", "teclas"]
    assert [caminho for caminho, _ in cliente.escrito] == [
        GAME_SETTINGS,
        INPUT_SETTINGS,
    ]
    assert cliente.escrito[1][1] == TECLAS


def test_an_old_snapshot_never_rewrites_the_video_mode():
    """Fotografia de uma versão anterior não pode mexer na tela.

    O modo de vídeo é o que a captura do minimapa lê; reescrevê-lo por
    baixo do jogador seria o app brigando com o próprio aviso.
    """
    cliente = ClienteFalso()
    apply(cliente, {"game": {"General": {"WindowMode": 0, "CursorScale": 1}}})

    assert cliente.escrito[0][1] == {"General": {"CursorScale": 1}}


def test_a_snapshot_with_nothing_in_it_writes_nothing():
    cliente = ClienteFalso()

    assert apply(cliente, {}) == []
    assert cliente.escrito == []


# --- a troca de conta ---------------------------------------------------


def test_the_copy_waits_for_the_client_to_finish_loading():
    """O cliente ainda está baixando a conta nova quando anuncia."""
    agora, tempo = relogio([100.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com_modelo(), now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    sync.tick()
    assert cliente.escrito == []

    tempo["agora"] = 100.0 + APPLY_DELAYS[0]
    sync.tick()
    assert len(cliente.escrito) == 2


def test_the_copy_happens_twice_because_the_client_may_be_late():
    """Se o cliente escreveu por cima da primeira, a segunda corrige."""
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com_modelo(), now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    for espera in APPLY_DELAYS:
        tempo["agora"] = espera
        sync.tick()
    tempo["agora"] = APPLY_DELAYS[-1] * 10
    sync.tick()

    assert len(cliente.escrito) == 4


def test_the_main_account_does_not_receive_a_copy_of_itself():
    """A principal é o modelo. Copiar nela seria escrever à toa."""
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    contas = com_modelo()
    sync = GameSettingsSync(cliente, contas, now=agora)

    sync.account_arrived(quem())
    tempo["agora"] = 1000.0
    sync.tick()

    assert cliente.escrito == []


def test_without_a_model_nothing_is_touched():
    """Quem nunca guardou nada não tem as teclas mexidas por engano."""
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    sync = GameSettingsSync(cliente, contas, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    tempo["agora"] = 1000.0
    sync.tick()

    assert cliente.escrito == []


def test_a_second_switch_replaces_the_first_schedule():
    """Trocar de conta duas vezes seguidas não escreve pela conta velha."""
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    contas = com_modelo()
    sync = GameSettingsSync(cliente, contas, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    sync.account_arrived(quem())  # voltou para a principal
    tempo["agora"] = 1000.0
    sync.tick()

    assert cliente.escrito == []


def test_asking_for_it_now_does_not_wait():
    """O botão é para quando o cliente escreveu por cima da cópia."""
    agora, _ = relogio([0.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com_modelo(), now=agora)

    sync.request_apply("amigo#br2@br")
    sync.tick()

    assert len(cliente.escrito) == 2


def test_asking_without_a_model_explains_instead_of_writing():
    ditas: list[str] = []
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    sync = GameSettingsSync(ClienteFalso(), contas, log=ditas.append)

    sync.request_apply()
    sync.tick()

    assert any("Nenhuma configuração de jogo guardada" in linha for linha in ditas)


# --- guardar ------------------------------------------------------------


def test_capturing_stores_the_snapshot_and_writes_it_down():
    contas = com_modelo()
    contas.set_game_settings(contas.main, {})
    gravou: list[bool] = []
    avisou: list[bool] = []
    sync = GameSettingsSync(
        ClienteFalso(),
        contas,
        save=lambda: gravou.append(True),
        on_change=lambda: avisou.append(True),
    )

    sync.request_capture(contas.main)
    sync.tick()

    guardado = contas.main_game_settings()
    assert guardado["input"] == TECLAS
    assert "Performance" not in guardado["game"]
    assert gravou == [True]
    assert avisou == [True]


def test_capturing_an_unknown_account_stores_nothing():
    contas = com_modelo()
    gravou: list[bool] = []
    sync = GameSettingsSync(ClienteFalso(), contas, save=lambda: gravou.append(True))

    sync.request_capture("ninguem")
    sync.tick()

    assert gravou == []


def test_an_empty_answer_is_never_stored_as_a_model():
    """Fotografia vazia viraria uma cópia que apaga nada e promete tudo."""
    ditas: list[str] = []
    contas = com_modelo()
    contas.set_game_settings(contas.main, {})
    sync = GameSettingsSync(
        ClienteFalso(jogo={}, teclas={}), contas, log=ditas.append
    )

    sync.request_capture(contas.main)
    sync.tick()

    assert contas.main_game_settings() == {}
    assert any("não devolveu as configurações" in linha for linha in ditas)


def test_clearing_the_model_stops_the_copy():
    """Apagar a fotografia é como o usuário desliga a cópia."""
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    contas = com_modelo()
    contas.set_game_settings(contas.main, {})
    sync = GameSettingsSync(cliente, contas, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    tempo["agora"] = 1000.0
    sync.tick()

    assert cliente.escrito == []


# --- quando o cliente diz não -------------------------------------------


def test_a_client_that_refuses_to_read_never_breaks_the_switch():
    ditas: list[str] = []
    contas = com_modelo()
    contas.set_game_settings(contas.main, {})
    sync = GameSettingsSync(
        ClienteFalso(erro="deu ruim"), contas, log=ditas.append
    )

    sync.request_capture(contas.main)
    sync.tick()

    assert contas.main_game_settings() == {}
    assert any("Não consegui ler" in linha for linha in ditas)


def test_a_client_that_refuses_to_write_gives_up_quietly():
    """Falhar em escrever não pode virar tentativa infinita."""
    agora, tempo = relogio([0.0])
    ditas: list[str] = []
    cliente = ClienteFalso(erro="deu ruim")
    sync = GameSettingsSync(cliente, com_modelo(), log=ditas.append, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    for espera in APPLY_DELAYS:
        tempo["agora"] = espera
        sync.tick()

    assert sum("Não consegui aplicar" in linha for linha in ditas) == 1


def test_a_disk_that_says_no_does_not_lose_the_switch():
    def falhar() -> None:
        raise OSError("disco cheio")

    ditas: list[str] = []
    contas = com_modelo()
    sync = GameSettingsSync(ClienteFalso(), contas, save=falhar, log=ditas.append)

    sync.request_capture(contas.main)
    sync.tick()

    assert any("gravar as contas" in linha for linha in ditas)


# --- o perfil no disco --------------------------------------------------


def test_the_model_survives_the_settings_of_the_app_changing():
    """Mexer nos ajustes do app não apaga a fotografia do jogo."""
    contas = com_modelo()
    contas.remember(contas.main, Config(flash_key="f"))

    assert contas.main_game_settings()["input"] == TECLAS


def test_the_model_survives_logging_in_again():
    contas = com_modelo()
    contas.arrive(quem(), Config())

    assert contas.main_game_settings()["input"] == TECLAS


def test_the_model_survives_closing_the_app(tmp_path):
    alvo = tmp_path / "contas.json"
    contas = com_modelo()
    contas.save(alvo)

    lidas = Accounts.load(alvo)

    assert lidas.main_game_settings()["game"]["HUD"]["MinimapScale"] == 0.8


def test_a_history_from_an_older_version_has_no_model(tmp_path):
    alvo = tmp_path / "contas.json"
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    contas.save(alvo)

    assert Accounts.load(alvo).main_game_settings() == {}


def test_forgetting_the_account_takes_the_model_with_it():
    contas = com_modelo()
    contas.forget(account_key(quem()))

    assert contas.main_game_settings() == {}


@pytest.mark.parametrize("torto", [None, [], "não é dicionário", 7])
def test_a_broken_snapshot_is_ignored_instead_of_crashing(torto):
    assert apply(ClienteFalso(), torto) == []
    assert strip_machine(torto) == {}
