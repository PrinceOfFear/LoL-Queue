"""Geometria da página Campeões em uma janela compacta."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.binding import ConfigBinder  # noqa: E402
from lolqueue.ui.pages.champions import ChampionsPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_two_priority_cards_fit_a_compact_window_without_horizontal_scroll(app):
    """Os dois cartões continuam lado a lado no tamanho do app do usuário."""
    page = ChampionsPage(ConfigBinder(Config()))
    page.resize(1000, 674)
    page.show()
    app.processEvents()

    grids = page.findChildren(QtWidgets.QListWidget, "championGrid")

    assert page.width() == 1000
    assert len(grids) == 2
    assert all(grid.horizontalScrollBar().maximum() == 0 for grid in grids)

    page.close()
