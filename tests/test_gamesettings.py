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
    MAX_ROUNDS,
    RETRY_DELAY,
    GameSettingsSync,
    apply,
    capture,
    mismatches,
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


def test_a_pending_manual_apply_is_cancelled_after_switching_accounts():
    """O clique não pode alcançar a conta que entrou logo depois."""
    ditas: list[str] = []
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com_modelo(), log=ditas.append)
    sync.account_arrived(quem("Amigo", "BR2"))
    sync.request_apply("amigo#br2@br")
    sync.account_arrived(quem())

    sync.tick()

    assert cliente.escrito == []
    assert any("pedido antigo foi cancelado" in linha for linha in ditas)


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


def test_a_pending_capture_is_cancelled_after_switching_accounts():
    """A fotografia precisa pertencer à conta que ainda está na LCU."""
    ditas: list[str] = []
    contas = com_modelo()
    contas.set_game_settings(contas.main, {})
    sync = GameSettingsSync(ClienteFalso(), contas, log=ditas.append)
    sync.account_arrived(quem())
    sync.request_capture(contas.main)
    sync.account_arrived(quem("Amigo", "BR2"))

    sync.tick()

    assert contas.main_game_settings() == {}
    assert any("pedido antigo foi cancelado" in linha for linha in ditas)


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


# --- a conferência ------------------------------------------------------
#
# O PATCH responde 2xx e mesmo assim não gruda: na troca de conta o
# cliente ainda está baixando os ajustes de quem entrou e escreve por
# cima logo depois. Sem conferir, o app anunciava sucesso e o jogador
# clicava no botão à mão sete vezes seguidas, foi o que o diário de
# 29/08 mostrou. Daqui para baixo é a prova de que ele confere.


#: Uma fotografia que o `ClienteFalso` NÃO devolve — sem isso nenhum
#: teste veria divergência, porque o modelo de `com_modelo` é
#: exatamente o que o cliente falso responde.
TEIMOSO = {"game": {"HUD": {"MinimapScale": 1.5}}, "input": TECLAS}


def com(modelo):
    """Duas contas, com a fotografia que o teste escolher."""
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    contas.arrive(quem("Amigo", "BR2"), Config())
    contas.set_game_settings(contas.main, modelo)
    return contas


def test_a_key_the_client_omits_is_not_a_mismatch():
    """O cliente cala o que está no padrão dele.

    Cobrar essas chaves reprovaria para sempre uma cópia que pegou, e a
    insistência viraria um laço que nunca converge.
    """
    cliente = ClienteFalso(jogo={"HUD": {"MinimapScale": 0.8}}, teclas={})
    modelo = {"game": {"HUD": {"MinimapScale": 0.8, "FlipMiniMap": True}}}

    assert mismatches(cliente, modelo) == []


def test_a_key_the_client_answers_differently_is_a_mismatch():
    assert mismatches(ClienteFalso(), TEIMOSO) == ["interface: HUD/MinimapScale"]


def test_the_copy_is_written_again_when_it_did_not_stick():
    """E a nova rodada entra na fila na ordem certa.

    A segunda passada de `APPLY_DELAYS` cai em 25s; a repetição, em 20s.
    Como `tick` só olha o primeiro da fila, uma repetição empilhada no
    fim ficaria presa atrás dela — a fila tem de estar ordenada.
    """
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com(TEIMOSO), now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    tempo["agora"] = APPLY_DELAYS[0]
    sync.tick()
    assert len(cliente.escrito) == 2

    tempo["agora"] = APPLY_DELAYS[0] + RETRY_DELAY
    sync.tick()

    assert len(cliente.escrito) == 4


def test_the_insisting_has_an_end():
    """Insistir para sempre encheria o diário e nunca convenceria o cliente."""
    ditas: list[str] = []
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com(TEIMOSO), log=ditas.append, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    for _ in range(20):
        tempo["agora"] += RETRY_DELAY + 1.0
        sync.tick()

    assert len(cliente.escrito) == 2 * MAX_ROUNDS
    assert sum("não aceitou" in linha for linha in ditas) == 1


def test_the_copy_only_announces_success_once_per_arrival():
    """Duas passadas de propósito, uma frase só — senão parece defeito."""
    ditas: list[str] = []
    agora, tempo = relogio([0.0])
    sync = GameSettingsSync(ClienteFalso(), com_modelo(), log=ditas.append, now=agora)

    sync.account_arrived(quem("Amigo", "BR2"))
    for espera in APPLY_DELAYS:
        tempo["agora"] = espera
        sync.tick()

    # "Valem a partir" e não "aplicadas nesta conta": o aviso de que a
    # cópia *vai* acontecer usa quase as mesmas palavras.
    assert sum("Valem a partir" in linha for linha in ditas) == 1


def test_the_button_answers_even_when_it_did_not_stick():
    """Houve um clique esperando resposta; calar é o que fazia clicar de novo."""
    ditas: list[str] = []
    agora, _tempo = relogio([0.0])
    sync = GameSettingsSync(ClienteFalso(), com(TEIMOSO), log=ditas.append, now=agora)

    sync.request_apply("amigo#br2@br")
    sync.tick()

    assert any("ainda não aceitou" in linha for linha in ditas)


# --- o silêncio tem preferência ----------------------------------------


def test_what_the_silence_holds_survives_the_copy():
    """As duas escrevem em `GAME_SETTINGS`; só uma pode ganhar.

    A fotografia da conta principal tem o chat ligado, e sem esta
    ressalva a cópia desligava metade do silêncio de antes da partida —
    o "de lado fica meio muda" do relato.
    """
    cliente = ClienteFalso()
    segurado = {"Chat": {"EnableChat": False}, "HUD": {"ShowAlliedChat": False}}
    modelo = {
        "game": {
            "Chat": {"EnableChat": True},
            "HUD": {"ShowAlliedChat": True, "MinimapScale": 0.8},
        },
        "input": {},
    }

    apply(cliente, modelo, segurado)
    corpo = cliente.escrito[0][1]

    assert corpo["Chat"]["EnableChat"] is False
    assert corpo["HUD"]["ShowAlliedChat"] is False
    # E o resto da cópia continua acontecendo: a ressalva é cirúrgica.
    assert corpo["HUD"]["MinimapScale"] == 0.8


def test_the_copy_asks_the_silence_before_writing():
    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    modelo = {"game": {"HUD": {"ShowAlliedChat": True}}, "input": {}}
    sync = GameSettingsSync(
        cliente,
        com(modelo),
        now=agora,
        hold=lambda: {"HUD": {"ShowAlliedChat": False}},
    )

    sync.account_arrived(quem("Amigo", "BR2"))
    tempo["agora"] = APPLY_DELAYS[0]
    sync.tick()

    assert cliente.escrito[0][1]["HUD"]["ShowAlliedChat"] is False


def test_a_silence_that_breaks_does_not_take_the_copy_down():
    """Perguntar é uma cortesia; a cópia não depende da resposta."""

    def explode() -> dict:
        raise RuntimeError("o silêncio caiu")

    agora, tempo = relogio([0.0])
    cliente = ClienteFalso()
    sync = GameSettingsSync(cliente, com_modelo(), now=agora, hold=explode)

    sync.account_arrived(quem("Amigo", "BR2"))
    tempo["agora"] = APPLY_DELAYS[0]
    sync.tick()

    assert len(cliente.escrito) == 2
