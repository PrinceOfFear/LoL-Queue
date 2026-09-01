import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.seguranca import SecurityCheck, SecurityReport, SecurityState  # noqa: E402
from lolqueue.ui.widgets.security_card import SecurityCard  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_security_card_shows_local_results_and_one_clear_action(app):
    card = SecurityCard()
    report = SecurityReport(
        (
            SecurityCheck("updates", "ATUALIZAÇÕES ASSINADAS", "Tudo certo.", SecurityState.PASSED),
            SecurityCheck("integrity", "INTEGRIDADE", "Sem selo ainda.", SecurityState.WARNING),
        )
    )

    card.show_report(report)

    assert card._badge.text() == "PARCIAL"
    assert card._badge.property("state") == "warning"
    assert card._checks.count() == 2
    assert card._action.text() == "Verificar novamente"

    called = []
    card.check_requested.connect(lambda: called.append(True))
    card._action.click()
    assert called == [True]
