"""Os três resumos do painel devem retratar a configuração real da conta."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.binding import ConfigBinder  # noqa: E402
from lolqueue.ui.pages.dashboard import DashboardPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def contextual_page(app, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    config = Config(
        queue_id=420,
        primary_position="middle",
        secondary_position="jungle",
        flash_key="f",
        opgg_tier="grandmaster",
    )
    binder = ConfigBinder(config)
    return config, binder, DashboardPage(binder=binder)


def test_cards_start_with_the_real_routes_flash_key_and_build_elo(contextual_page):
    _config, _binder, page = contextual_page

    assert page._route_feature.icon_keys == ("middle", "jungle")
    assert page._route_feature.detail_label.text() == "Meio + Selva"
    assert all(not label.pixmap().isNull() for label in page._route_feature.icon_labels)
    assert page._flash_feature.icon_keys == ("flash",)
    assert page._flash_feature.detail_label.text() == "Sempre no F"
    assert page._build_feature.icon_keys == ("grandmaster",)
    assert page._build_feature.detail_label.text() == "Grão-Mestre"


def test_cards_redraw_immediately_after_a_setting_changes(contextual_page):
    _config, binder, page = contextual_page

    binder.set("primary_position", "top")
    binder.set("secondary_position", "utility")
    binder.set("flash_key", "d")
    binder.set("opgg_tier", "emerald_plus")

    assert page._route_feature.icon_keys == ("top", "utility")
    assert page._route_feature.detail_label.text() == "Topo + Suporte"
    assert page._flash_feature.detail_label.text() == "Sempre no D"
    assert page._build_feature.icon_keys == ("emerald_plus",)
    assert page._build_feature.detail_label.text() == "Esmeralda+"


def test_account_reload_replaces_content_and_hides_the_old_second_route(
    contextual_page,
):
    config, binder, page = contextual_page

    config.primary_position = "fill"
    config.secondary_position = ""
    config.flash_key = "auto"
    config.opgg_tier = "silver"
    binder.reload()

    assert page._route_feature.icon_keys == ("fill",)
    assert page._route_feature.detail_label.text() == "Qualquer rota"
    assert page._route_feature.icon_labels[1].isHidden()
    assert page._flash_feature.detail_label.text() == "Como já estiver na conta"
    assert page._build_feature.icon_keys == ("silver",)
    assert page._build_feature.detail_label.text() == "Prata"


def test_a_queue_without_role_selection_does_not_claim_routes_are_active(
    contextual_page,
):
    config, binder, page = contextual_page

    config.queue_id = 450
    binder.reload()

    assert page._route_feature.icon_keys == ("unselected",)
    assert page._route_feature.detail_label.text() == "Esta fila não usa rotas"
