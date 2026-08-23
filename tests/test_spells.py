"""O catálogo de feitiços de invocador: ícone por id."""

from lolqueue.core.spells import SpellCatalog
from lolqueue.lcu import endpoints

from .fakes import FakeLcuClient

#: Recorte de `/lol-game-data/assets/v1/summoner-spells.json`, com dados reais.
SPELLS = [
    {"id": 4, "iconPath": "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_flash.png"},
    {"id": 12, "iconPath": "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_teleport.png"},
]


def catalog(responses=None, failures=None):
    client = FakeLcuClient(
        responses={endpoints.SUMMONER_SPELLS: SPELLS, **(responses or {})},
        failures=failures,
    )
    loaded = SpellCatalog(client)
    loaded.load()
    return loaded, client


def test_the_catalog_learns_the_icon():
    spells, _ = catalog()

    assert spells.icon_path(4) == "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_flash.png"


def test_a_spell_it_never_heard_of_has_no_icon():
    spells, _ = catalog()

    assert spells.icon_path(404) == ""


def test_a_failed_load_leaves_the_catalog_empty_not_wrong():
    spells, _ = catalog(failures={endpoints.SUMMONER_SPELLS})

    assert not spells.loaded
    assert spells.icon_path(4) == ""


def test_the_catalog_is_only_fetched_once():
    spells, client = catalog()
    spells.load()

    assert client.paths("GET").count(endpoints.SUMMONER_SPELLS) == 1


def test_the_icon_list_has_no_repeats():
    spells, _ = catalog()

    paths = spells.icons()
    assert len(paths) == len(set(paths))
    assert all(paths)
