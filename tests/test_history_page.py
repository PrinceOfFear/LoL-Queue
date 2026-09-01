"""A página de histórico: o que mostra, e quando volta ao vazio."""

import os
from dataclasses import replace
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from lolqueue.core.lp_history import LP_SOURCE_MANUAL  # noqa: E402
from lolqueue.core.summoner_history import (  # noqa: E402
    GameDetail,
    MatchSummary,
    ParticipantDetail,
    Profile,
    RankEntry,
    TeamDetail,
)
from lolqueue.ui.pages.history import (  # noqa: E402
    HISTORY_ITEM_COLUMNS,
    HISTORY_ITEM_ICON,
    HISTORY_ITEMS_WIDTH,
    SCOREBOARD_ITEM_ICON,
    SCOREBOARD_ITEMS_WIDTH,
    HistoryPage,
)


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


def test_the_ranked_profile_uses_the_official_crest(page):
    page.set_history(profile(), ())

    crests = page.findChildren(QtWidgets.QLabel, "rankCrestSmall")
    assert len(crests) == 1
    assert crests[0].pixmap() is not None
    assert not crests[0].pixmap().isNull()


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


def test_the_match_row_shows_the_official_lp_delta_when_available(page):
    page.set_history(profile(), (match(lp_delta=21),))

    row = page._matches_box.itemAt(0).widget()
    lp = row.findChildren(QtWidgets.QLabel, "lpDelta")
    assert len(lp) == 1
    assert lp[0].text() == "+21 PDL"
    assert lp[0].property("direction") == "gain"


def test_the_match_row_does_not_invent_lp_for_an_old_match(page):
    page.set_history(profile(), (match(),))

    row = page._matches_box.itemAt(0).widget()
    lp = row.findChildren(QtWidgets.QLabel, "lpDelta")
    assert len(lp) == 1
    assert lp[0].text() == "N/D"
    assert lp[0].property("direction") == "unavailable"


def test_manual_lp_button_offers_only_a_uniquely_linked_ranked_nd(page):
    eligible = match(local_game_id=998877)
    page.set_history(profile(), (eligible, match(queue_type="ARAM", local_game_id=123)))
    seen = []
    page.manual_lp_import_requested.connect(lambda matches: seen.append(matches))

    page._manual_import_button.click()

    assert page.manual_lp_matches() == (eligible,)
    assert seen == [(eligible,)]


def test_manual_lp_is_labeled_as_informed_not_as_a_riot_confirmation(page):
    page.set_history(
        profile(),
        (match(lp_delta=-18, lp_source=LP_SOURCE_MANUAL, local_game_id=998877),),
    )

    row = page._matches_box.itemAt(0).widget()
    lp_box = row.findChild(QtWidgets.QFrame, "historyLpBox")

    assert lp_box is not None
    assert lp_box.property("source") == LP_SOURCE_MANUAL
    assert "informado manualmente" in lp_box.toolTip()


def test_the_match_row_draws_every_item_the_match_really_has(page):
    page.set_history(profile(), (match(items=(1001, 1002, 1003)),))

    row = page._matches_box.itemAt(0).widget()
    icons = row.findChildren(QtWidgets.QLabel, "itemIcon")
    assert len(icons) == 3


def test_history_items_use_a_larger_compact_grid(page):
    page.set_history(
        profile(),
        (match(items=(1001, 1002, 1003, 1004, 1005, 1006, 3363)),),
    )

    row = page._matches_box.itemAt(0).widget()
    holder = row.findChild(QtWidgets.QFrame, "historyItems")
    icons = holder.findChildren(QtWidgets.QLabel, "itemIcon")

    assert len(icons) == 7
    assert all(icon.minimumSize() == HISTORY_ITEM_ICON for icon in icons)
    assert holder.minimumWidth() == HISTORY_ITEMS_WIDTH
    assert holder.maximumWidth() == HISTORY_ITEMS_WIDTH
    assert holder.layout().columnCount() == HISTORY_ITEM_COLUMNS
    assert holder.layout().rowCount() == 2


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


def test_scoreboard_items_are_larger_but_keep_their_reserved_column(page):
    items = (1001, 1002, 1003, 1004, 1005, 1006, 3363)
    names = tuple(f"Item {index}" for index in range(1, 8))
    page.set_history(profile(), (match(),))
    page.set_game_detail(
        detail(
            teams=(
                team(participants=(participant(items=items, item_names=names),)),
                team(key="RED", win=True, participants=(participant(team_key="RED"),)),
            )
        )
    )

    blue_team = page._teams_box.itemAt(0).widget()
    holder = blue_team.findChild(QtWidgets.QWidget, "scoreboardItems")
    assert holder is not None
    icons = holder.findChildren(QtWidgets.QLabel, "itemIcon")
    assert len(icons) == 7
    assert SCOREBOARD_ITEM_ICON == QSize(40, 40)
    assert all(icon.minimumSize() == SCOREBOARD_ITEM_ICON for icon in icons)
    assert all(icon.property("fullBleed") is True for icon in icons)
    assert all(not icon.hasScaledContents() for icon in icons)
    assert holder.minimumWidth() == SCOREBOARD_ITEMS_WIDTH
    assert holder.maximumWidth() == SCOREBOARD_ITEMS_WIDTH
    assert icons[0].toolTip() == "Item 1"


def test_scoreboard_item_art_fills_its_cell_without_stretching(page, tmp_path):
    source = tmp_path / "wide-item.png"
    image = QImage(80, 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    assert image.save(str(source))

    icon = page._icon_label(
        "itemIcon",
        SCOREBOARD_ITEM_ICON,
        lambda _: str(source),
        1001,
        full_bleed=True,
    )

    # Uma fonte não quadrada é ampliada e recortada pelo centro, sem ser
    # deformada. Os itens do LoL são quadrados, então em produção a arte usa
    # exatamente a célula de 40 x 40 sem borda interna.
    assert icon.pixmap().size() == QSize(80, 40)
    assert icon.size() == SCOREBOARD_ITEM_ICON
    assert icon.alignment() == Qt.AlignmentFlag.AlignCenter
    assert not icon.hasScaledContents()


def test_the_scoreboard_shows_each_players_damage_with_a_relative_bar(page):
    blue = tuple(
        participant(
            team_key="BLUE",
            is_target=(i == 0),
            game_name=f"P{i}",
            damage_to_champions=(i + 1) * 1000,
        )
        for i in range(5)
    )
    red = tuple(
        participant(
            team_key="RED",
            game_name=f"R{i}",
            damage_to_champions=(i + 6) * 1000,
        )
        for i in range(5)
    )
    full_detail = detail(
        teams=(
            team(key="BLUE", win=False, participants=blue),
            team(key="RED", win=True, participants=red),
        )
    )
    page.set_history(profile(), (match(),))

    page.set_game_detail(full_detail)

    values = page._scoreboard_view.findChildren(QtWidgets.QLabel, "damageValue")
    bars = page._scoreboard_view.findChildren(QtWidgets.QProgressBar, "damageBar")
    assert len(values) == 10
    assert "10.000" in [value.text() for value in values]
    assert len(bars) == 10
    assert all(bar.maximum() == 10000 for bar in bars)
    assert max(bar.value() for bar in bars) == 10000


def test_the_scoreboard_repeats_the_lp_delta_for_the_open_match(page):
    page.set_history(profile(), (match(lp_delta=-18),))

    page.set_game_detail(detail(lp_delta=-18))

    assert "−18 PDL" in page._scoreboard_subtitle.text()


def test_an_open_scoreboard_receives_lp_that_arrived_after_its_details(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())

    page.set_history(profile(), (match(lp_delta=21),))

    assert not page._scoreboard_view.isHidden()
    assert "+21 PDL" in page._scoreboard_subtitle.text()


def test_scoreboard_uses_one_damage_header_for_each_team(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())

    headers = page._scoreboard_view.findChildren(
        QtWidgets.QLabel, "scoreboardColumnLabel"
    )
    assert [header.text() for header in headers].count("DANO A CAMPEÕES") == 2
    assert not page._scoreboard_view.findChildren(QtWidgets.QLabel, "damageCaption")


def test_scoreboard_headers_and_rows_share_the_same_column_geometry(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())
    page.resize(862, 1050)
    page.show()
    QTest.qWait(1)

    team_card = page._teams_box.itemAt(0).widget()
    header = team_card.findChild(QtWidgets.QFrame, "scoreboardColumns")
    row = team_card.findChildren(QtWidgets.QFrame, "optionCard")[0]
    header_grid = header.layout()
    row_grid = row.layout()

    header_cells = [
        header.mapTo(team_card, header_grid.cellRect(0, column).topLeft()).x()
        for column in range(7)
    ]
    row_cells = [
        row.mapTo(team_card, row_grid.cellRect(0, column).topLeft()).x()
        for column in range(7)
    ]
    assert header_cells == row_cells
    # Mesmo abaixo da largura ideal, a coluna fixa dos sete itens não pode
    # encostar nas métricas ao lado. O QScrollArea da janela cuida da rolagem
    # quando necessário; aqui a grade continua íntegra e alinhada.
    item_rect = row_grid.cellRect(0, 3)
    kda_rect = row_grid.cellRect(0, 4)
    economy_rect = row_grid.cellRect(0, 5)
    damage_rect = row_grid.cellRect(0, 6)
    assert item_rect.width() >= SCOREBOARD_ITEMS_WIDTH
    assert item_rect.right() < kda_rect.left()
    assert kda_rect.right() < economy_rect.left()
    assert economy_rect.right() < damage_rect.left()
    champions = page._scoreboard_view.findChildren(
        QtWidgets.QLabel, "scoreboardChampion"
    )
    assert champions and all(champion.width() > 0 for champion in champions)


def test_long_summoner_names_do_not_widen_the_scoreboard(page):
    normal_detail = detail()
    page.set_history(profile(), (match(),))
    page.set_game_detail(normal_detail)
    normal_minimum = page._scoreboard_view.minimumSizeHint().width()

    long_blue_team = replace(
        normal_detail.teams[0],
        participants=tuple(
            replace(
                participant,
                game_name="NomeDeInvocadorMuitoLongoParaUmaLinha",
                tag_line="TAGMUITOLONGA",
            )
            for participant in normal_detail.teams[0].participants
        ),
    )
    page.set_game_detail(replace(normal_detail, teams=(long_blue_team, normal_detail.teams[1])))

    assert page._scoreboard_view.minimumSizeHint().width() <= normal_minimum


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
