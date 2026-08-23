"""O catálogo de itens: ícone por id, carregado uma vez do cliente."""

from lolqueue.core.items import ItemCatalog
from lolqueue.lcu import endpoints

from .fakes import FakeLcuClient

#: Recorte de `/lol-game-data/assets/v1/items.json`, com dados reais.
ITEMS = [
    {
        "id": 3153,
        "iconPath": "/lol-game-data/assets/ASSETS/Items/Icons2D/3153_Fighter_T3_BladeOfTheRuinedKing.png",
    },
    {"id": 1001, "iconPath": "/lol-game-data/assets/ASSETS/Items/Icons2D/1001_Boots.png"},
]


def catalog(responses=None, failures=None):
    client = FakeLcuClient(
        responses={endpoints.ITEMS: ITEMS, **(responses or {})},
        failures=failures,
    )
    loaded = ItemCatalog(client)
    loaded.load()
    return loaded, client


def test_the_catalog_learns_the_icon():
    items, _ = catalog()

    assert items.icon_path(3153) == (
        "/lol-game-data/assets/ASSETS/Items/Icons2D/3153_Fighter_T3_BladeOfTheRuinedKing.png"
    )


def test_an_item_it_never_heard_of_has_no_icon():
    items, _ = catalog()

    assert items.icon_path(404) == ""


def test_a_failed_load_leaves_the_catalog_empty_not_wrong():
    items, _ = catalog(failures={endpoints.ITEMS})

    assert not items.loaded
    assert items.icon_path(3153) == ""


def test_the_catalog_is_only_fetched_once():
    items, client = catalog()
    items.load()

    assert client.paths("GET").count(endpoints.ITEMS) == 1


def test_the_icon_list_has_no_repeats():
    items, _ = catalog()

    paths = items.icons()
    assert len(paths) == len(set(paths))
    assert all(paths)
