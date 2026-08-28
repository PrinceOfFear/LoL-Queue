"""Reordenar a prioridade de dentro da Central de Fila.

Pedido do usuário: mudar a ordem dos campeões sem sair da tela em que a
partida está acontecendo. O que se arrasta aqui tem que ser a lista que
o motor vai consultar — e a página Campeões tem que concordar com ela.
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
    # O watcher abre thread e fala com o cliente do LoL; a fiação entre o
    # painel e a config não precisa de nenhum dos dois.
    monkeypatch.setattr(MainWindow, "_start_watcher", lambda self: None)
    config = Config(
        auto_pick=True,
        pick_priority=[64, 11, 63],
        pick_priority_by_position={"utility": [11, 63]},
    )
    return MainWindow(config)


def panel(window):
    return window._dashboard._order


def move_up(window, row):
    """Sobe uma linha do painel como o usuário faria pelo botão."""
    panel(window)._list.setCurrentRow(row)
    panel(window)._up.click()


def test_the_panel_starts_on_the_general_list(window):
    assert panel(window).ids() == [64, 11, 63]


def test_reordering_writes_the_general_list(window):
    move_up(window, 1)
    assert window._config.pick_priority == [11, 64, 63]


def test_reordering_reaches_the_champions_page(window):
    """Sem isso a outra página desfaria a decisão no arrasto seguinte."""
    move_up(window, 1)
    assert window._champions.pick_picker.general() == [11, 64, 63]


def test_a_route_with_its_own_list_is_the_one_shown(window):
    window._on_pick_scope_changed("utility")
    assert panel(window).ids() == [11, 63]


def test_a_route_with_its_own_list_is_the_one_written(window):
    window._on_pick_scope_changed("utility")
    move_up(window, 1)
    assert window._config.pick_priority_by_position["utility"] == [63, 11]
    # A geral não pode ser tocada de raspão pela edição da rota.
    assert window._config.pick_priority == [64, 11, 63]


def test_a_route_without_its_own_list_edits_the_general_one(window):
    window._on_pick_scope_changed("jungle")
    assert panel(window).ids() == [64, 11, 63]
    move_up(window, 2)
    assert window._config.pick_priority == [64, 63, 11]
    assert "jungle" not in window._config.pick_priority_by_position


def test_leaving_champion_select_goes_back_to_the_general_list(window):
    window._on_pick_scope_changed("utility")
    window._on_pick_scope_changed("")
    assert panel(window).ids() == [64, 11, 63]


def test_the_champions_page_updates_the_central(window):
    """A ligação vale para os dois lados: as duas telas editam o mesmo."""
    window._champions.pick_picker._picker.changed.emit([63, 64, 11])
    assert panel(window).ids() == [63, 64, 11]


def test_receiving_an_order_does_not_echo_back(window):
    """O repasse à página Campeões não pode voltar como nova gravação."""
    ecos: list = []
    window._champions.pick_picker.changed.connect(
        lambda position, ids: ecos.append((position, list(ids)))
    )
    move_up(window, 1)
    assert ecos == []


def test_the_panel_says_when_automation_is_off(window, app):
    """Ordem caprichada com a escolha automática desligada não vale nada."""
    window._binder.set("auto_pick", False)
    assert "desligada" in panel(window)._scope.text()
