"""A página de leitura: o que ela mostra e o que ela esconde.

Quase tudo aqui é sobre esconder. Os campos de leitura são opcionais —
vêm de carona na resposta que o equipamento já pede — e cada seção some
sozinha quando o dado dela não veio. Um cartão de confrontos vazio
parece defeito e não é, e essa distinção é o que estes testes guardam.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.core.matchup import Matchup  # noqa: E402
from lolqueue.core.opgg import Build, Counter, Stats, Synergy  # noqa: E402
from lolqueue.ui.pages.analysis import AnalysisPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app):
    return AnalysisPage()


def build(**changes):
    base = dict(
        style=8000,
        sub_style=8300,
        perks=(1, 2, 3, 4, 5, 6, 7, 8, 9),
        spells=(4, 12),
        skill_order=tuple("QEWQQRQEQEREEWW"),
        skill_max=("Q", "E", "W"),
        strong_against=(Counter(39, "Irelia", 0.56, 900),),
        weak_against=(Counter(136, "Aurelion Sol", 0.41, 400),),
        synergies=(Synergy(76, "Nidalee", "JUNGLE", 0.54, 300),),
        stats=Stats(12000, 0.49, 0.12, 0.17, 1.62, 3, 44),
        damage_type="AD",
    )
    base.update(changes)
    return Build(**base)


# --- o vazio --------------------------------------------------------------


def test_it_starts_with_nothing_to_read(page):
    assert page._content.isHidden()
    assert not page._empty.isHidden()


def test_a_build_that_never_came_keeps_the_empty_notice(page):
    """Consulta falhada não vira tela em branco com cartões vazios."""
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "Diamante+", None)

    assert page._content.isHidden()


def test_a_champion_without_a_name_shows_nothing(page):
    page.set_analysis("", "", None, "middle", "", build())

    assert page._content.isHidden()


# --- o que aparece --------------------------------------------------------


def test_it_names_the_champion_and_says_where_he_plays(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "Diamante+", build())

    assert page._name.text() == "Yasuo"
    assert "Meio" in page._where.text()
    assert "Diamante+" in page._where.text()


def test_the_build_tier_is_also_shown_as_an_official_crest(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "Diamante+", build())

    assert not page._tier_crest.isHidden()
    assert page._tier_crest.pixmap() is not None
    assert not page._tier_crest.pixmap().isNull()


def test_the_damage_type_is_said_in_words(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    assert "Dano físico" in page._where.text()


def test_a_damage_type_we_do_not_know_is_kept_as_it_came(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build(damage_type="TRUE"))

    assert "TRUE" in page._where.text()


def test_the_skill_order_becomes_one_cell_per_level(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    # 15 casas mais o esticador do fim da fileira.
    assert page._skills._row.count() == 16


def test_the_ultimate_levels_are_marked_apart(page):
    """Níveis 6, 11 e 16 não são escolha, e a fileira precisa mostrar isso."""
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    marcadas = [
        i
        for i in range(15)
        if page._skills._row.itemAt(i).widget().property("ultimate") == "true"
    ]

    # Níveis 6 e 11 na contagem humana. O terceiro ponto de ultimato é o
    # 16, que não existe numa fileira de quinze.
    assert marcadas == [5, 10]


def test_the_max_priority_is_written_in_order(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    assert page._max_order.text() == "Q  >  E  >  W"


# --- as seções que somem --------------------------------------------------


def test_no_skill_data_hides_the_skill_card(page):
    page.set_analysis(
        "Yasuo", "Yasuo", None, "middle", "", build(skill_order=(), skill_max=())
    )

    assert page._skills_card.isHidden()


def test_no_counters_hides_the_counter_cards(page):
    page.set_analysis(
        "Yasuo", "Yasuo", None, "middle", "", build(strong_against=(), weak_against=())
    )

    assert page._counters_card.isHidden()


def test_no_synergies_hides_the_synergy_card(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build(synergies=()))

    assert page._synergies_card.isHidden()


def test_without_a_lane_there_is_no_lane_matchup(page):
    """No Abismo todos dividem a mesma faixa: a pergunta não se aplica."""
    page.set_analysis("Yasuo", "Yasuo", None, "", "", build())

    assert page._matchup_card.isHidden()


def test_with_a_lane_the_matchup_card_is_offered(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    assert not page._matchup_card.isHidden()


# --- o seletor de adversário ----------------------------------------------


def test_choosing_an_opponent_asks_for_the_guide(page):
    pedidos = []
    page.matchup_requested.connect(lambda alias, lane: pedidos.append((alias, lane)))
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])

    page._opponent.setCurrentIndex(1)

    assert pedidos == [("Zed", "middle")]


def test_the_placeholder_asks_for_nothing(page):
    pedidos = []
    page.matchup_requested.connect(lambda alias, lane: pedidos.append(alias))
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])
    page._opponent.setCurrentIndex(1)
    pedidos.clear()

    page._opponent.setCurrentIndex(0)

    assert pedidos == []


def test_the_name_of_the_opponent_is_the_one_the_player_reads(page):
    """O alias vai para o OP.GG; o nome é o que aparece na aba do arsenal."""
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Wukong", "MonkeyKing")])

    page._opponent.setCurrentIndex(1)

    assert page.opponent_name == "Wukong"


def test_with_nobody_chosen_there_is_no_opponent_name(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Wukong", "MonkeyKing")])

    assert page.opponent_name == ""


def test_the_list_sends_the_alias_not_the_name(page):
    """Wukong é `MonkeyKing` no OP.GG: mandar o nome não acha ninguém."""
    pedidos = []
    page.matchup_requested.connect(lambda alias, lane: pedidos.append(alias))
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Wukong", "MonkeyKing")])

    page._opponent.setCurrentIndex(1)

    assert pedidos == ["MonkeyKing"]


def test_reloading_the_catalogue_keeps_the_chosen_opponent(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed"), ("Riven", "Riven")])
    page._opponent.setCurrentIndex(2)

    page.set_champions([("Zed", "Zed"), ("Riven", "Riven"), ("Ahri", "Ahri")])

    assert page._opponent.currentData() == "Riven"


def test_a_new_champion_clears_the_old_matchup(page):
    """A dica na tela era do boneco anterior e não vale para este."""
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])
    page._opponent.setCurrentIndex(1)
    page.set_matchup("Zed", Matchup("Yasuo", "Zed", "cuidado", "Zed", "", "Equilibrado"))

    page.set_analysis("Riven", "Riven", None, "top", "", build())

    assert page._tip.isHidden()
    assert page._opponent.currentIndex() == 0


# --- o guia que volta -----------------------------------------------------


def test_the_guide_is_written_on_the_card(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])
    page._opponent.setCurrentIndex(1)

    page.set_matchup(
        "Zed", Matchup("Yasuo", "Zed", "Bloqueie o Q.", "Zed", "Yasuo", "Agressivo")
    )

    assert page._tip.text() == "Bloqueie o Q."
    assert "Vantagem na rota: Zed" in page._verdict.text()
    assert "Duelo isolado: Yasuo" in page._verdict.text()
    assert "Ritmo: Agressivo" in page._verdict.text()


def test_an_even_lane_is_said_in_words(page):
    """Vantagem vazia é rota parelha, e não um campo faltando."""
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])
    page._opponent.setCurrentIndex(1)

    page.set_matchup("Zed", Matchup("Yasuo", "Zed", "cuidado", "", "", "Equilibrado"))

    assert "Rota parelha" in page._verdict.text()


def test_a_late_answer_for_someone_else_is_ignored(page):
    """Trocar de adversário duas vezes deixa a primeira resposta atrasada.

    Sem a conferência ela sobrescreve a segunda, e a tela passa a falar
    de um confronto que já não é o escolhido.
    """
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed"), ("Riven", "Riven")])
    page._opponent.setCurrentIndex(2)

    page.set_matchup("Zed", Matchup("Yasuo", "Zed", "dica do Zed", "Zed", "", ""))

    assert page._tip.isHidden()


def test_a_matchup_the_server_does_not_know_says_so(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())
    page.set_champions([("Zed", "Zed")])
    page._opponent.setCurrentIndex(1)

    page.set_matchup("Zed", None)

    assert "não tem dados" in page._matchup_state.text()
    assert page._tip.isHidden()


# --- o boletim ------------------------------------------------------------


def test_the_stats_become_labelled_measures(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build())

    textos = []
    for i in range(page._stats.count()):
        bloco = page._stats.itemAt(i).widget()
        textos.extend(
            bloco.layout().itemAt(j).widget().text() for j in range(bloco.layout().count())
        )

    assert "49%" in textos
    assert "1.62" in textos
    assert "Bom · #44" in textos


def test_a_champion_without_stats_shows_no_measures(page):
    page.set_analysis("Yasuo", "Yasuo", None, "middle", "", build(stats=None))

    assert page._stats.count() == 0
