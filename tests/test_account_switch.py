"""Troca de conta vista da tela: o perfil chega aos widgets.

`tests/test_accounts.py` cobre o modelo — quem herda de quem, o que vai
para o disco. Aqui é a outra metade: entrar em outra conta tem que
redesenhar a janela, sem que o redesenho volte gravando o que acabou de
carregar. Foi o eco que quase custou os ajustes da conta anterior.

A config é redirecionada para um diretório temporário, e com ela o
arquivo de contas, que mora ao lado — por isso `accounts_path` vive na
config e não no módulo das contas.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.core import watcher as watcher_module  # noqa: E402
from lolqueue.core.identity import Identity  # noqa: E402
from lolqueue.core.watcher import PhaseWatcher  # noqa: E402
from lolqueue.ui.window import MainWindow  # noqa: E402


def quem(nome: str = "Thiago", tag: str = "BR1") -> Identity:
    return Identity(game_name=nome, tag_line=tag, region="BR", level=300)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(MainWindow, "_start_watcher", lambda self: None)
    return MainWindow(
        Config(
            auto_pick=True,
            queue_id=420,
            flash_key="d",
            primary_position="jungle",
            ban_priority=[63],
        )
    )


def test_the_first_account_takes_the_settings_that_were_already_there(window):
    """Quem já usava o app não perde nada ao ganhar perfis."""
    window._on_identity_changed(quem())

    assert window._accounts.main == "thiago#br1@br"
    assert window._config.flash_key == "d"
    assert window._settings._flash.currentData() == "d"


def test_coming_back_to_an_account_redraws_the_whole_screen(window):
    """O que a conta tinha volta para os widgets, não só para a config."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))

    window._binder.set("flash_key", "f")
    window._binder.set("queue_id", 440)
    window._binder.boxes("auto_pick")[0].setChecked(False)

    window._on_identity_changed(quem())

    assert window._settings._flash.currentData() == "d"
    assert window._queue._combo.currentData() == 420
    assert window._binder.boxes("auto_pick")[0].isChecked() is True
    assert window._config.auto_pick is True


def test_the_redraw_does_not_write_back_over_the_profile(window):
    """Redesenhar não é mexer: um eco aqui gravaria na conta errada."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))
    window._binder.set("flash_key", "f")

    visto = []
    window._binder.changed.connect(visto.append)
    window._on_identity_changed(quem())

    assert visto == []
    assert window._accounts.accounts["amigo#br2@br"].settings["flash_key"] == "f"


def test_the_champion_lists_follow_the_account(window):
    """A lista de banimento é do jogador, não do computador."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))

    window._champions.ban_picker.set_ids([64])
    window._champions.ban_picker._emit()
    window._on_identity_changed(quem())

    assert window._champions.ban_picker.ids() == [63]


def test_the_lanes_follow_the_account(window):
    """Rota pedida é preferência pessoal, e some junto com a conta."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))
    window._binder.set("primary_position", "")

    assert window._queue._secondary.isEnabled() is False

    window._on_identity_changed(quem())

    assert window._queue._primary.currentData() == "jungle"
    assert window._queue._secondary.isEnabled() is True


def test_an_account_that_never_came_here_starts_with_the_main_one(window):
    """Conta emprestada abre com o app do dono do PC."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Emprestada", "BR9"))

    assert window._settings._flash.currentData() == "d"
    assert window._queue._primary.currentData() == "jungle"


def test_forgetting_an_account_takes_it_off_the_card(window):
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))
    window._on_forget_account("thiago#br1@br")

    assert "thiago#br1@br" not in window._accounts
    assert window._accounts.main == ""


def test_the_history_survives_closing_the_app(window, tmp_path):
    """O perfil só vale se estiver no disco quando o app abrir de novo."""
    window._on_identity_changed(quem())
    window._binder.set("flash_key", "f")

    from lolqueue.core.accounts import Accounts

    lidas = Accounts.load(tmp_path / "contas.json")

    assert lidas.accounts["thiago#br1@br"].settings["flash_key"] == "f"


# --- o anúncio da conta, na thread do watcher ---------------------------


def watcher_falando(monkeypatch, respostas):
    """Um watcher que responde a identidade da vez, sem rede."""
    fila = iter(respostas)
    monkeypatch.setattr(
        watcher_module, "current_identity", lambda client: next(fila, respostas[-1])
    )
    watcher = PhaseWatcher(lambda client: None)
    visto = []
    watcher.identity_changed.connect(visto.append)
    return watcher, visto


def test_the_same_account_is_announced_only_once(monkeypatch):
    """Perguntar de dez em dez segundos não é trocar de conta."""
    watcher, visto = watcher_falando(monkeypatch, [quem(), quem()])

    watcher._check_identity(object())
    watcher._check_identity(object())

    assert len(visto) == 1


def test_another_account_is_announced(monkeypatch):
    watcher, visto = watcher_falando(monkeypatch, [quem(), quem("Amigo", "BR2")])

    watcher._check_identity(object())
    watcher._check_identity(object())

    assert [identidade.game_name for identidade in visto] == ["Thiago", "Amigo"]


def test_the_engine_hears_the_switch_on_the_thread_that_has_the_client(monkeypatch):
    """A cópia das configurações do jogo precisa da LCU, que só existe
    nesta thread — por isso o aviso vai direto ao motor, sem passar
    pela janela."""
    watcher, _ = watcher_falando(monkeypatch, [quem()])
    ouvidas = []
    watcher._engine = type(
        "MotorFalso", (), {"handle_identity": lambda self, i: ouvidas.append(i)}
    )()

    watcher._check_identity(object())

    assert [identidade.game_name for identidade in ouvidas] == ["Thiago"]


def test_an_incomplete_answer_is_not_a_switch(monkeypatch):
    """Cliente subindo responde pela metade; isso não reconfigura nada."""
    watcher, visto = watcher_falando(monkeypatch, [None, None])

    watcher._check_identity(object())

    assert visto == []


# --- as configurações de dentro do jogo, vistas do cartão ---------------


def botoes(window) -> list[str]:
    """Os botões das linhas desenhadas agora.

    Pelo layout e não por `findChildren`: as linhas antigas saem com
    `deleteLater`, que sem laço de eventos ainda não rodou, e elas
    apareceriam aqui como se estivessem na tela.
    """
    linhas = window._settings.accounts._rows
    textos = []
    for indice in range(linhas.count()):
        linha = linhas.itemAt(indice).widget()
        if linha is not None:
            textos += [b.text() for b in linha.findChildren(QtWidgets.QPushButton)]
    return textos


def test_only_the_account_that_is_logged_in_offers_to_save_the_game_settings(window):
    """Só dá para ler o jogo da conta que o cliente tem na mão."""
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))
    window._on_identity_changed(quem())

    assert "Guardar config do jogo" in botoes(window)
    assert botoes(window).count("Guardar config do jogo") == 1


def test_an_account_that_is_not_the_main_one_gets_the_button_to_receive(window):
    """Rede de segurança para quando o cliente escreve por cima."""
    window._on_identity_changed(quem())
    window._accounts.set_game_settings(window._accounts.main, {"input": {"a": 1}})
    window._on_identity_changed(quem("Amigo", "BR2"))

    assert "Aplicar config do jogo" in botoes(window)
    assert "Guardar config do jogo" not in botoes(window)


def test_without_a_model_nobody_is_offered_a_copy(window):
    window._on_identity_changed(quem())
    window._on_identity_changed(quem("Amigo", "BR2"))

    assert "Aplicar config do jogo" not in botoes(window)


def test_stopping_the_copy_erases_the_model(window):
    window._on_identity_changed(quem())
    window._accounts.set_game_settings(window._accounts.main, {"input": {"a": 1}})
    window._on_clear_game(window._accounts.main)

    assert window._accounts.main_game_settings() == {}
    assert "Parar de copiar" not in botoes(window)


def test_asking_without_the_client_open_explains_instead_of_failing(window):
    """Sem cliente aberto não há o que ler; isso não pode virar crash."""
    ditas = []
    window._log_message = ditas.append
    window._on_identity_changed(quem())

    window._on_capture_game(window._accounts.main)
    window._on_apply_game(window._accounts.main)

    assert [linha for linha in ditas if "Abra o cliente do LoL" in linha] == [
        "Abra o cliente do LoL para guardar as configurações do jogo.",
        "Abra o cliente do LoL para aplicar as configurações do jogo.",
    ]


def test_the_note_is_left_for_the_thread_that_holds_the_client(window):
    """A janela não fala com a LCU: ela deixa o bilhete e segue."""
    from lolqueue.core.gamesettings import GameSettingsSync

    window._on_identity_changed(quem())
    window._game_sync = GameSettingsSync(object(), window._accounts)
    window._on_capture_game(window._accounts.main)

    assert window._game_sync._capture == window._accounts.main
