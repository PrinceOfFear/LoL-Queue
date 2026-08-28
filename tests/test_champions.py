import lolqueue.core.champions as champions_module
from lolqueue.core.champions import ChampionCatalog
from lolqueue.lcu import endpoints
from lolqueue.lcu.client import LcuError
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


class FlakyClient(FakeLcuClient):
    """Falha nas primeiras N chamadas a um caminho, depois responde normal.

    `FakeLcuClient.failures` falha sempre — não serve para simular a
    corrida de inicialização, onde a API do LCU já responde mas um
    endpoint específico só fica pronto um instante depois.
    """

    def __init__(self, fail_times, **kwargs):
        super().__init__(**kwargs)
        self._fail_times = dict(fail_times)

    def get(self, path):
        self.calls.append(("GET", path))
        remaining = self._fail_times.get(path, 0)
        if remaining > 0:
            self._fail_times[path] = remaining - 1
            raise LcuError(f"ainda não, {path}")
        return self.responses.get(path)


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


def test_it_knows_the_riot_alias():
    """O nome de exibição é traduzido; o alias não.

    Num cliente em português "Nunu & Willump" vira "Nunu e Willump",
    e sites de fora não reconhecem isso. O alias é o mesmo em toda
    parte, e é ele que serve para conversar com terceiros.
    """
    catalog = make_catalog()
    catalog.load()
    assert catalog.alias(64) == "LeeSin"


def test_an_unknown_champion_has_no_alias():
    catalog = make_catalog()
    catalog.load()
    assert catalog.alias(999) == ""


# --- corrida de inicialização: API de pé, dados estáticos ainda não ------
#
# Ao reconectar bem no instante em que o cliente do LoL termina de subir, a
# API já aceita chamadas mas `CHAMPION_SUMMARY` pode responder erro por
# mais um instante. Antes, `load()` engolia isso pra sempre e nada
# chamava de novo — o catálogo ficava vazio pelo resto da conexão.


def test_load_with_retries_recovers_from_a_slow_start(monkeypatch):
    monkeypatch.setattr(champions_module.time, "sleep", lambda _: None)
    client = FlakyClient(
        {endpoints.CHAMPION_SUMMARY: 2},
        responses={endpoints.CHAMPION_SUMMARY: SUMMARY},
    )
    catalog = ChampionCatalog(client)

    catalog.load_with_retries()

    assert catalog.loaded is True
    assert catalog.name(64) == "Lee Sin"
    assert client.paths("GET").count(endpoints.CHAMPION_SUMMARY) == 3


def test_load_with_retries_gives_up_after_the_bound_and_stays_tolerant(monkeypatch):
    """Se a falha for de verdade (não só o instante da corrida), desiste.

    Sem limite, uma falha permanente do endpoint travaria a reconexão
    pra sempre — o resto do app já sabe seguir com o catálogo vazio.
    """
    monkeypatch.setattr(champions_module.time, "sleep", lambda _: None)
    client = FlakyClient(
        {endpoints.CHAMPION_SUMMARY: 999},
        responses={endpoints.CHAMPION_SUMMARY: SUMMARY},
    )
    catalog = ChampionCatalog(client)

    catalog.load_with_retries(attempts=3, delay=0.01)

    assert catalog.loaded is False
    assert catalog.all() == []
    assert client.paths("GET").count(endpoints.CHAMPION_SUMMARY) == 3


def test_load_with_retries_does_not_sleep_after_succeeding_on_the_first_try(
    monkeypatch,
):
    slept = []
    monkeypatch.setattr(champions_module.time, "sleep", slept.append)
    catalog = make_catalog()

    catalog.load_with_retries()

    assert catalog.loaded is True
    assert slept == []
