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


def test_drops_mode_variants_that_duplicate_real_champions():
    """O cliente devolve ~60 cópias de campeões feitas para outros modos.

    Vêm com o mesmo `name` do original e um alias namespaced
    (`Jade_MasterYi`), mas com ids na casa dos 60000 que a seleção
    normal nunca aceita. Sem filtrar, a grade mostra cada campeão duas
    vezes e metade dos cliques salva uma escolha que nunca funciona.
    """
    catalog = make_catalog(
        SUMMARY + [{"id": 60011, "name": "Master Yi", "alias": "Jade_MasterYi"}]
    )
    catalog.load()
    assert catalog.knows(60011) is False
    assert [name for _, name in catalog.all()] == ["Lee Sin", "Master Yi"]
    # O clone vinha depois na lista e sequestrava a busca por nome.
    assert catalog.id_for("master yi") == 11


def test_knows_only_the_ids_that_came_from_the_client():
    catalog = make_catalog()
    catalog.load()
    assert catalog.knows(64) is True
    assert catalog.knows(60079) is False


def test_an_unloaded_catalog_claims_to_know_nothing_yet():
    """Sem catálogo carregado, `knows` é falso para tudo.

    Quem for podar uma lista com base nisso precisa checar `loaded`
    antes, senão apaga as escolhas do usuário numa falha de rede.
    """
    catalog = make_catalog(failures={endpoints.CHAMPION_SUMMARY})
    catalog.load()
    assert catalog.knows(64) is False


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
