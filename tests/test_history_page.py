"""A página de histórico: o que mostra, e quando volta ao vazio."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from lolqueue.core.summoner_history import (  # noqa: E402
    GameDetail,
    MatchSummary,
    ParticipantDetail,
    Profile,
    RankEntry,
    TeamDetail,
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


def participant(**changes):
    base = dict(
        is_target=False,
        game_name="Jogador",
        tag_line="BR1",
        champion_id=54,
        champion_name="Malphite",
        team_key="BLUE",
        position="TOP",
        items=(1056, 3802, 1001),
        item_names=("Anel de Doran", "Capítulo Perdido", "Botas"),
        spells=(4, 12),
        primary_style_id=8200,
        primary_rune_id=8229,
        secondary_style_id=8400,
        champion_level=10,
        kills=0,
        deaths=4,
        assists=0,
        cs=79,
        gold=3901,
        damage_to_champions=4790,
        result="LOSE",
    )
    base.update(changes)
    return ParticipantDetail(**base)


def team(**changes):
    base = dict(
        key="BLUE",
        win=False,
        kills=8,
        towers=0,
        dragons=0,
        barons=0,
        heralds=0,
        gold=24155,
        banned_champion_ids=(25, 55, 141, 412, 910),
        banned_champion_names=("Morgana", "Katarina", "Kayn", "Thresh", "Hwei"),
        participants=tuple(
            participant(team_key="BLUE", is_target=(i == 0), game_name=f"P{i}")
            for i in range(5)
        ),
    )
    base.update(changes)
    return TeamDetail(**base)


def detail(**changes):
    base = dict(
        match_id="abc",
        duration_seconds=958,
        queue_type="SOLORANKED",
        played_at=datetime(2026, 8, 23, 8, 18, 49, tzinfo=timezone.utc),
        teams=(
            team(key="BLUE", win=False),
            team(
                key="RED",
                win=True,
                participants=tuple(
                    participant(team_key="RED", is_target=False, game_name=f"R{i}")
                    for i in range(5)
                ),
            ),
        ),
        average_tier="EMERALD",
    )
    base.update(changes)
    return GameDetail(**base)


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


def test_the_match_row_has_a_win_lose_stripe_and_a_level_badge(page):
    page.set_history(profile(), (match(champion_level=15, result="WIN"),))

    row = page._matches_box.itemAt(0).widget()
    assert row.property("result") == "win"
    badges = row.findChildren(QtWidgets.QLabel, "levelBadge")
    assert len(badges) == 1
    assert badges[0].text() == "15"


def test_a_lost_match_row_is_marked_lose(page):
    page.set_history(profile(), (match(result="LOSE"),))

    row = page._matches_box.itemAt(0).widget()
    assert row.property("result") == "lose"


def test_the_match_row_draws_every_item_the_match_really_has(page):
    page.set_history(profile(), (match(items=(1001, 1002, 1003)),))

    row = page._matches_box.itemAt(0).widget()
    icons = row.findChildren(QtWidgets.QLabel, "itemIcon")
    assert len(icons) == 3


def test_the_match_row_draws_the_keystone_and_the_secondary_style(page):
    page.set_history(profile(), (match(),))

    row = page._matches_box.itemAt(0).widget()
    icons = row.findChildren(QtWidgets.QLabel, "runeIcon")
    assert len(icons) == 2


def test_the_match_row_draws_both_summoner_spells(page):
    page.set_history(profile(), (match(),))

    row = page._matches_box.itemAt(0).widget()
    icons = row.findChildren(QtWidgets.QLabel, "spellIcon")
    assert len(icons) == 2


def test_clicking_a_row_emits_the_match_it_represents(page):
    target = match(match_id="xyz")
    page.set_history(profile(), (target,))
    seen = []
    page.match_selected.connect(lambda m: seen.append(m))

    row = page._matches_box.itemAt(0).widget()
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)

    assert seen == [target]


def test_set_game_detail_shows_the_scoreboard_and_hides_the_list(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    assert page._list_view.isHidden()
    assert not page._scoreboard_view.isHidden()


def test_the_scoreboard_shows_both_teams_with_five_players_each(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    assert page._teams_box.count() == 2
    for i in range(2):
        block = page._teams_box.itemAt(i).widget()
        rows = block.findChildren(QtWidgets.QFrame, "optionCard")
        assert len(rows) == 5


def test_the_target_participant_is_marked(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    marked = []
    for i in range(2):
        block = page._teams_box.itemAt(i).widget()
        for row in block.findChildren(QtWidgets.QFrame, "optionCard"):
            if row.property("target") == "true":
                marked.append(row)
    assert len(marked) == 1


def test_a_missing_game_detail_returns_to_the_list(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())

    page.set_game_detail(None)

    assert not page._list_view.isHidden()
    assert page._scoreboard_view.isHidden()


def test_the_back_button_returns_to_the_list(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())

    page._back_button.click()

    assert not page._list_view.isHidden()
    assert page._scoreboard_view.isHidden()


def test_the_scoreboard_colors_each_row_by_team(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    blue_block = page._teams_box.itemAt(0).widget()
    red_block = page._teams_box.itemAt(1).widget()
    blue_rows = blue_block.findChildren(QtWidgets.QFrame, "optionCard")
    red_rows = red_block.findChildren(QtWidgets.QFrame, "optionCard")
    assert len(blue_rows) == 5 and len(red_rows) == 5
    assert all(row.property("team") == "blue" for row in blue_rows)
    assert all(row.property("team") == "red" for row in red_rows)


def test_the_target_row_wears_a_you_badge(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    badges = page._scoreboard_view.findChildren(QtWidgets.QLabel, "youBadge")
    assert len(badges) == 1


def test_set_loading_relabels_and_disables_the_refresh_button(page):
    page.set_loading(True)

    assert page._refresh_button.isEnabled() is False
    assert "Atualizando" in page._refresh_button.text()

    page.set_loading(False)

    assert page._refresh_button.isEnabled() is True
    assert page._refresh_button.text() == "Atualizar"


def test_set_history_clears_a_loading_state_left_over(page):
    page.set_loading(True)

    page.set_history(profile(), ())

    assert page._refresh_button.isEnabled() is True


def test_set_game_detail_clears_a_loading_state_left_over(page):
    page.set_history(profile(), (match(),))
    page.set_loading(True)

    page.set_game_detail(detail())

    assert page._refresh_button.isEnabled() is True


def test_a_missing_game_detail_also_clears_the_loading_state(page):
    page.set_history(profile(), (match(),))
    page.set_loading(True)

    page.set_game_detail(None)

    assert page._refresh_button.isEnabled() is True


def test_the_refresh_button_asks_for_a_new_query(page):
    seen = []
    page.refresh_requested.connect(lambda: seen.append(True))

    page._refresh_button.click()

    assert seen == [True]
