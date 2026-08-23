"""A página de histórico: o que mostra, e quando volta ao vazio."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.core.summoner_history import (  # noqa: E402
    MatchSummary,
    Profile,
    RankEntry,
)
from lolqueue.ui.pages.history import HistoryPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app):
    return HistoryPage()


def profile(**changes):
    base = dict(
        game_name="Jogador",
        tag_line="BR1",
        level=1098,
        ranks=(
            RankEntry("SOLORANKED", "EMERALD", 3, 53, 602, 602),
            RankEntry("ARENA", None, None, None, 0, 0),
        ),
    )
    base.update(changes)
    return Profile(**base)


def match(**changes):
    base = dict(
        match_id="abc",
        champion_id=22,
        champion_name="Ashe",
        result="WIN",
        kills=6,
        deaths=6,
        assists=12,
        cs=188,
        duration_seconds=1686,
        queue_type="SOLORANKED",
        position="ADC",
        played_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc),
        items=(1001, 1002),
        item_names=("Botas", "Espada Longa"),
        spells=(4, 12),
        primary_style_id=8200,
        primary_rune_id=8229,
        secondary_style_id=8400,
        champion_level=15,
        gold=8902,
    )
    base.update(changes)
    return MatchSummary(**base)


def test_it_starts_with_nothing_to_read(page):
    assert page._content.isHidden()
    assert not page._empty.isHidden()


def test_a_profile_that_never_came_keeps_the_empty_notice(page):
    page.set_history(None, ())

    assert page._content.isHidden()
    assert not page._empty.isHidden()


def test_a_full_profile_shows_name_and_level(page):
    page.set_history(profile(), (match(),))

    assert page._content.isVisible() or not page._content.isHidden()
    assert "Jogador#BR1" in page._name.text()
    assert "1098" in page._level.text()


def test_the_match_row_shows_champion_and_kda(page):
    page.set_history(profile(), (match(),))

    row_layout = page._matches_box.itemAt(0).widget().layout()
    texts = []

    def collect(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                texts.append(widget.text() if hasattr(widget, "text") else "")
            elif item.layout() is not None:
                collect(item.layout())

    collect(row_layout)
    joined = " ".join(texts)
    assert "Ashe" in joined
    assert "6/6/12" in joined


def test_the_refresh_button_asks_for_a_new_query(page):
    seen = []
    page.refresh_requested.connect(lambda: seen.append(True))

    page._refresh_button.click()

    assert seen == [True]
