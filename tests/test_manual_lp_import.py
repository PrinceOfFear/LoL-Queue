from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.core.summoner_history import MatchSummary  # noqa: E402
from lolqueue.ui.widgets.manual_lp_import import (  # noqa: E402
    ManualLpImportDialog,
    parse_manual_delta,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _match(**changes):
    values = {
        "match_id": "opaque",
        "champion_id": 54,
        "champion_name": "Malphite",
        "result": "WIN",
        "kills": 8,
        "deaths": 5,
        "assists": 1,
        "cs": 185,
        "duration_seconds": 1200,
        "queue_type": "SOLORANKED",
        "position": "TOP",
        "played_at": datetime(2026, 8, 31, 18, 30, tzinfo=timezone.utc),
        "items": (),
        "item_names": (),
        "spells": (4, 12),
        "primary_style_id": 8200,
        "primary_rune_id": 8229,
        "secondary_style_id": 8400,
        "champion_level": 14,
        "gold": 10000,
        "local_game_id": 998877,
    }
    values.update(changes)
    return MatchSummary(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("+22", 22),
        ("-18", -18),
        ("−18", -18),
        ("0", 0),
        ("+0", 0),
        ("22", None),
        ("-", None),
        ("", None),
    ),
)
def test_manual_delta_requires_an_explicit_direction(text, expected):
    assert parse_manual_delta(text) == expected


def test_dialog_turns_only_valid_filled_rows_into_manual_inputs(app):
    dialog = ManualLpImportDialog((_match(),))
    field = dialog.findChild(QtWidgets.QLineEdit, "manualLpInput")
    assert field is not None

    field.setText("-18")
    dialog.accept()

    rows = dialog.inputs()
    assert len(rows) == 1
    assert rows[0].game_id == 998877
    assert rows[0].queue_id == 420
    assert rows[0].delta == -18


def test_dialog_leaves_it_open_when_a_nonzero_delta_has_no_sign(app):
    dialog = ManualLpImportDialog((_match(),))
    field = dialog.findChild(QtWidgets.QLineEdit, "manualLpInput")
    assert field is not None
    field.setText("22")

    dialog.accept()

    assert dialog.inputs() == ()
    assert not dialog._error.isHidden()
