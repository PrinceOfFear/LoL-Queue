"""Fiação da janela: o que a tela promete tem que bater com a config.

O watcher fica de fora — ele abre thread e fala com o cliente do LoL, e
nada disso é necessário para conferir a ligação entre widget e config.

A config é redirecionada para um diretório temporário: a janela grava a
cada mudança, e sem isso o teste sobrescreveria a config de verdade do
usuário.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(MainWindow, "_start_watcher", lambda self: None)
    config = Config(
        auto_pick=True,
        auto_ban=True,
        pick_priority=[64],
        ban_priority=[63],
    )
    return MainWindow(config)


def boxes(window, attribute):
    return window._binder.boxes(attribute)


def test_the_same_setting_has_a_switch_next_to_its_list(window):
    """O interruptor tem que estar onde a lista está.

    Só na página de Automação ele ficava longe demais: dava para encher
    a lista inteira sem perceber que a automação estava desligada.
    """
    assert len(boxes(window, "auto_pick")) == 2
    assert len(boxes(window, "auto_ban")) == 2


def test_switching_one_switch_moves_the_other(window):
    first, second = boxes(window, "auto_pick")

    first.setChecked(False)

    assert second.isChecked() is False
    assert window._config.auto_pick is False


def test_the_switches_do_not_bounce_off_each_other(window):
    """A caixa que só reflete fica muda: reflete, não decide.

    Sem o bloqueio ela emitiria `toggled` ao ser alinhada, e o eco
    voltaria para a config para gravar de novo o que já estava lá.
    """
    first, second = boxes(window, "auto_ban")

    seen = []
    second.toggled.connect(seen.append)
    first.setChecked(False)

    assert seen == []
    assert second.isChecked() is False
    assert window._config.auto_ban is False


def test_turning_the_pick_automation_off_shows_up_on_the_list(window):
    boxes(window, "auto_pick")[0].setChecked(False)

    assert "desligada" in window._champions.pick_picker.notice()


def test_turning_the_ban_automation_off_shows_up_on_the_list(window):
    boxes(window, "auto_ban")[0].setChecked(False)

    assert "desligado" in window._champions.ban_picker.notice()


def test_emptying_the_ban_list_warns_that_nothing_is_banned(window):
    window._champions.ban_picker.set_ids([])
    window._champions.ban_picker._emit()

    assert "banido" in window._champions.ban_picker.notice()


def test_an_empty_general_list_warns_which_lanes_pick_nothing(window):
    """A config real do usuário chegou nesse estado sem nenhum aviso."""
    window._champions.pick_picker._picker.set_ids([])
    window._champions.pick_picker._picker._emit()

    assert "TOPO" in window._champions.pick_picker.notice()


def test_the_window_saves_what_the_switches_change(window, tmp_path):
    boxes(window, "auto_pick")[0].setChecked(False)

    assert Config.load(tmp_path / "config.json").auto_pick is False


def test_every_message_is_also_written_to_the_file(window, tmp_path):
    """O painel some ao fechar o app; o arquivo é o que sobra."""
    window._log_message("Banindo Brand.")

    written = (tmp_path / "registro").glob("*.log")
    assert any("Banindo Brand." in f.read_text(encoding="utf-8") for f in written)


def test_the_log_folder_sits_next_to_the_config(window, tmp_path):
    assert window._journal.directory == tmp_path / "registro"


# --- filas que a Riot desligou -------------------------------------------
#
# Quem descobre é o watcher, na thread dele; quem mostra é a página, na
# thread da GUI. A entrega vai pelo mesmo caminho do catálogo: um
# atributo simples, lido na primeira troca de fase.


def test_a_queue_the_client_refuses_is_marked_on_the_selector(window):
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    combo = window._queue._combo
    assert "indisponível" in combo.itemText(combo.findData(430))


def test_the_player_hears_about_it_when_the_queue_is_his_own(window, monkeypatch):
    said = []
    monkeypatch.setattr(window, "_log_message", said.append)
    window._config.queue_id = 430
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    assert any("Normal Blind" in line for line in said)


def test_nothing_is_said_when_the_chosen_queue_works(window, monkeypatch):
    said = []
    monkeypatch.setattr(window, "_log_message", said.append)
    window._config.queue_id = 420
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    assert said == []
