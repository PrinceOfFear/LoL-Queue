"""Contabilidade das listas por rota.

É o widget que decide o que vai para a config, então roda de verdade —
com Qt em modo offscreen, sem abrir janela nenhuma.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.ui.widgets.position_picker import (  # noqa: E402
    GENERAL,
    TAB_ORDER,
    PositionPicker,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def picker(app):
    return PositionPicker("ESCOLHA", [64], {"utility": [11]})


class FakeCatalog:
    """Catálogo que só reconhece 64 e 11."""

    loaded = True

    def knows(self, champion_id):
        return champion_id in (64, 11)

    def all(self):
        return [(11, "Master Yi"), (64, "Lee Sin")]

    def name(self, champion_id):
        return {11: "Master Yi", 64: "Lee Sin"}.get(champion_id, f"#{champion_id}")


def tab_index(key):
    return TAB_ORDER.index(key)


def test_opens_on_the_general_list(picker):
    assert picker.general() == [64]


def test_keeps_the_lists_of_each_position(picker):
    assert picker.by_position() == {"utility": [11]}


def test_switching_tabs_does_not_mix_the_lists(picker):
    picker._tabs.setCurrentIndex(tab_index("utility"))
    assert picker._picker.ids() == [11]
    picker._tabs.setCurrentIndex(tab_index(GENERAL))
    assert picker._picker.ids() == [64]


def test_editing_a_tab_reports_only_that_list(picker):
    recebido = []
    picker.changed.connect(lambda key, ids: recebido.append((key, list(ids))))
    picker._tabs.setCurrentIndex(tab_index("jungle"))
    picker._on_ids_changed([64])
    assert recebido == [("jungle", [64])]
    assert picker.general() == [64]
    assert picker.by_position() == {"utility": [11], "jungle": [64]}


def test_emptying_a_position_drops_it(picker):
    """Rota sem lista tem que sumir da config, não virar lista vazia.

    Guardada vazia, ela pareceria configurada na próxima abertura.
    """
    picker._tabs.setCurrentIndex(tab_index("utility"))
    picker._on_ids_changed([])
    assert picker.by_position() == {}


def test_the_catalog_prunes_every_tab_not_just_the_open_one(picker):
    """Id desconhecido escondido numa aba fechada nunca seria escolhido."""
    picker._tabs.setCurrentIndex(tab_index("top"))
    picker._on_ids_changed([64, 60079])
    picker._tabs.setCurrentIndex(tab_index(GENERAL))

    recebido = []
    picker.changed.connect(lambda key, ids: recebido.append((key, list(ids))))
    picker.set_catalog(FakeCatalog())

    assert picker.by_position()["top"] == [64]
    assert ("top", [64]) in recebido


def test_a_tab_with_its_own_list_is_marked(picker):
    marcada = picker._tabs.tabText(tab_index("utility"))
    vazia = picker._tabs.tabText(tab_index("jungle"))
    assert marcada.endswith("●")
    assert not vazia.endswith("●")
