import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.resources import asset_path  # noqa: E402
from lolqueue.ui.fonts import FONT_FILES, install_application_fonts  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_every_declared_interface_font_is_bundled():
    assert all(asset_path(relative).is_file() for relative in FONT_FILES)


def test_the_league_type_families_load_even_offscreen(app):
    families = install_application_fonts()

    assert "Spiegel" in families
    assert "Beaufort for LOL" in families
