from lolqueue.core.champions import ChampionCatalog
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

SUMMARY = [
    {"id": -1, "name": "Nenhum", "alias": "None"},
    {"id": 64, "name": "Lee Sin", "alias": "LeeSin"},
    {"id": 11, "name": "Master Yi", "alias": "MasterYi"},
]


def make_catalog(payload=SUMMARY, failures=None):
    client = FakeLcuClient(
        responses={endpoints.CHAMPION_SUMMARY: payload}, failures=failures
    )
    return ChampionCatalog(client)


def test_maps_id_to_name():
    catalog = make_catalog()
    catalog.load()
    assert catalog.name(64) == "Lee Sin"


def test_maps_name_to_id_case_insensitively():
    catalog = make_catalog()
    catalog.load()
    assert catalog.id_for("lee sin") == 64
    assert catalog.id_for("LEE SIN") == 64


def test_drops_the_sentinel_entry():
    catalog = make_catalog()
    catalog.load()
    assert all(champion_id > 0 for champion_id, _ in catalog.all())


def test_all_is_sorted_by_name():
    catalog = make_catalog()
    catalog.load()
    assert [name for _, name in catalog.all()] == ["Lee Sin", "Master Yi"]


def test_unknown_id_falls_back_to_the_number():
    catalog = make_catalog()
    catalog.load()
    assert catalog.name(9999) == "#9999"


def test_unknown_name_returns_none():
    catalog = make_catalog()
    catalog.load()
    assert catalog.id_for("Inexistente") is None


def test_failed_load_leaves_the_catalog_usable():
    catalog = make_catalog(failures={endpoints.CHAMPION_SUMMARY})
    catalog.load()
    assert catalog.loaded is False
    assert catalog.all() == []
    assert catalog.name(64) == "#64"


def test_load_only_hits_the_api_once():
    catalog = make_catalog()
    catalog.load()
    catalog.load()
    assert catalog._client.paths("GET").count(endpoints.CHAMPION_SUMMARY) == 1
