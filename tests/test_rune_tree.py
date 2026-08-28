"""A grade de runas desenhada na tela.

O que importa aqui não é a aparência, é que a grade some quando não há
página, que redesenhar não empilhe as fileiras antigas por baixo das
novas, e que a tela sobreviva a um catálogo que ainda não chegou.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.core.opgg import Build  # noqa: E402
from lolqueue.core.perks import PerkCatalog  # noqa: E402
from lolqueue.ui.pages.dashboard import DashboardPage  # noqa: E402
from lolqueue.ui.widgets.rune_tree import RuneTreeView  # noqa: E402
from lolqueue.ui.widgets.titlebar import TITLEBAR_HEIGHT  # noqa: E402
from lolqueue.ui.window import MINIMUM_HEIGHT  # noqa: E402

from .fakes import FakeLcuClient  # noqa: E402
from .test_perks import PAGINA, PERKS, STYLES  # noqa: E402
from lolqueue.lcu import endpoints  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def catalog():
    client = FakeLcuClient(
        responses={endpoints.PERKS: PERKS, endpoints.PERK_STYLES: STYLES}
    )
    loaded = PerkCatalog(client)
    loaded.load()
    return loaded


def build(**kwargs):
    base = dict(style=8000, sub_style=8200, perks=PAGINA, spells=(4, 11))
    base.update(kwargs)
    return Build(**base)


def slots(view):
    """Todas as casas desenhadas agora."""
    return [
        child
        for child in view.findChildren(QtWidgets.QFrame)
        if child.objectName() == "runeSlot"
    ]


# --- o widget -------------------------------------------------------------


def test_the_grid_draws_a_slot_for_every_option(app, catalog):
    """A árvore inteira aparece, não só o que foi escolhido."""
    view = RuneTreeView()

    view.set_tree(catalog.tree(8000, 8200, PAGINA), lambda url: None)

    # 2+2+1+2 na primária, 2+2+2 na secundária, 3+3+3 nos fragmentos.
    assert len(slots(view)) == 7 + 6 + 9


def test_the_chosen_runes_are_the_marked_ones(app, catalog):
    view = RuneTreeView()

    view.set_tree(catalog.tree(8000, 8200, PAGINA), lambda url: None)

    marcadas = [s for s in slots(view) if s.property("chosen") == "true"]
    # Quatro da primária, duas da secundária, três fragmentos.
    assert len(marcadas) == 9


def test_redrawing_does_not_pile_the_old_grid_underneath(app, catalog):
    """Trocar de elo redesenha; sem limpar, a grade ia crescendo."""
    view = RuneTreeView()
    tree = catalog.tree(8000, 8200, PAGINA)

    view.set_tree(tree, lambda url: None)
    antes = len(slots(view))
    view.set_tree(tree, lambda url: None)
    app.processEvents()  # `deleteLater` só age quando o laço roda

    assert len(slots(view)) == antes


def test_an_empty_tree_leaves_nothing_on_screen(app, catalog):
    view = RuneTreeView()
    view.set_tree(catalog.tree(8000, 8200, PAGINA), lambda url: None)

    view.set_tree(None)
    app.processEvents()

    assert slots(view) == []


def test_a_missing_icon_does_not_break_the_grid(app, catalog):
    """Ícone que ainda não baixou deixa a casa vazia, não derruba a tela."""
    view = RuneTreeView()

    view.set_tree(catalog.tree(8000, 8200, PAGINA), lambda url: None)

    assert len(slots(view)) == 22


# --- a ligação na página --------------------------------------------------


def test_the_page_draws_the_tree_of_the_applied_tier(app, catalog):
    page = DashboardPage()
    page.set_rune_catalog(catalog, lambda url: None)

    page.set_rune_options(
        ["diamond_plus", "master"],
        "master",
        {"diamond_plus": build(), "master": build(sub_style=8200)},
    )

    assert len(slots(page)) == 22


def test_the_page_survives_options_arriving_before_the_catalog(app, catalog):
    """O catálogo vem de uma thread lenta; as opções não esperam por ele.
    Sem catálogo a grade fica de fora e os botões de elo seguem valendo."""
    page = DashboardPage()

    page.set_rune_options(["master"], "master", {"master": build()})

    assert slots(page) == []
    assert page._runes.isHidden() is False


def test_the_catalog_arriving_late_draws_what_was_already_there(app, catalog):
    """E quando ele chega, a grade aparece sem esperar a próxima seleção."""
    page = DashboardPage()
    page.set_rune_options(["master"], "master", {"master": build()})

    page.set_rune_catalog(catalog, lambda url: None)

    assert len(slots(page)) == 22


def test_no_options_takes_the_grid_off_the_screen(app, catalog):
    page = DashboardPage()
    page.set_rune_catalog(catalog, lambda url: None)
    page.set_rune_options(["master"], "master", {"master": build()})

    page.set_rune_options([], None, {})
    app.processEvents()

    assert slots(page) == []
    assert page._runes.isHidden() is True


def test_without_an_applied_tier_the_grid_still_shows_something(app, catalog):
    """Quando as runas vieram da reserva da Riot não há elo marcado, mas
    deixar o painel oco seria pior do que mostrar a primeira que veio."""
    page = DashboardPage()
    page.set_rune_catalog(catalog, lambda url: None)

    page.set_rune_options(["master"], None, {"master": build()})

    assert len(slots(page)) == 22


def test_the_open_grid_still_fits_the_smallest_window(app, catalog):
    """A grade não pode empurrar o registro para fora da tela.

    Foi o que aconteceu quando ela nasceu: o painel passou a pedir mais
    altura do que a janela no tamanho mínimo tinha para dar, e o cartão
    de registro saía pela borda de baixo em vez de encolher.

    A medida aqui sai menor do que na máquina do usuário — sem as fontes
    reais o texto ocupa menos —, então o teste é um piso, não uma prova:
    ele pega o painel voltando a crescer, não garante o pixel exato.
    """
    page = DashboardPage()
    page.set_rune_catalog(catalog, lambda url: None)
    page.set_predicted_pick("Lee Sin", None)
    page.set_rune_options(
        ["diamond_plus", "master", "challenger"],
        "diamond_plus",
        {t: build() for t in ("diamond_plus", "master", "challenger")},
    )
    page.show()

    sobra = (MINIMUM_HEIGHT - TITLEBAR_HEIGHT) - page.minimumSizeHint().height()
    assert sobra >= 0


def test_a_build_whose_tree_is_unknown_draws_nothing(app, catalog):
    """Árvore que o catálogo não conhece não vira grade inventada."""
    page = DashboardPage()
    page.set_rune_catalog(catalog, lambda url: None)

    page.set_rune_options(["master"], "master", {"master": build(style=9999)})

    assert slots(page) == []
