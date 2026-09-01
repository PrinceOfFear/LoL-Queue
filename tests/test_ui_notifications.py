import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QUrl  # noqa: E402

from lolqueue.atualizacao import UpdateArtifact, UpdateOffer  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.binding import ConfigBinder  # noqa: E402
from lolqueue.ui.pages.settings import SettingsPage  # noqa: E402
from lolqueue.ui.widgets.sidebar import (  # noqa: E402
    WHATSAPP_CONTACT_URL,
    Sidebar,
)
from lolqueue.ui.widgets.update_notification import UpdateNotification  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _offer() -> UpdateOffer:
    return UpdateOffer(
        "0.2.0",
        "0.2.1",
        "Correções importantes.",
        UpdateArtifact(
            "standalone",
            "LoL Queue.zip",
            "0" * 64,
            1024,
            "LoL Queue",
            "https://example.com/LoL%20Queue.zip",
        ),
    )


def test_update_notification_is_hidden_until_a_signed_offer_is_ready(app):
    notification = UpdateNotification()

    assert not notification.isVisible()

    notification.show_offer(_offer())

    assert notification.isVisible()
    assert notification.offer.version == "0.2.1"
    assert notification._action.text() == "ATUALIZAR AGORA"

    notification._action.click()
    notification.hide_notification()
    assert not notification.isVisible()


def test_sidebar_contact_button_opens_the_public_whatsapp_link(app, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "lolqueue.ui.widgets.sidebar.QDesktopServices.openUrl",
        lambda url: opened.append(bytes(url.toEncoded()).decode()) or True,
    )
    sidebar = Sidebar()

    assert sidebar._contact_button.text() == "Fale conosco"
    assert "(64) 99296-1405" in sidebar._contact_button.toolTip()

    sidebar._contact_button.click()

    assert opened == [bytes(QUrl(WHATSAPP_CONTACT_URL).toEncoded()).decode()]
    assert "5564992961405" in opened[0]


def test_settings_keeps_security_check_internal_without_rendering_the_card(app):
    page = SettingsPage(ConfigBinder(Config()))

    assert page.security.isHidden()
    assert page.security.parentWidget() is page
