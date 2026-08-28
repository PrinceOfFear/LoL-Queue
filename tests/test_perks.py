"""O catálogo de runas e a grade que ele monta para a tela.

Os dados aqui são recortes fiéis do que o cliente responde: os ids, a
ordem das fileiras e a repetição de fragmentos entre elas são os de
verdade — é justamente essa repetição que a montagem tem de acertar.
"""

from lolqueue.core.perks import PerkCatalog
from lolqueue.lcu import endpoints

from .fakes import FakeLcuClient

#: Recorte de `/lol-perks/v1/perks`, só com o que a grade usa.
PERKS = [
    {"id": 8005, "name": "Ataque Certeiro", "iconPath": "/x/8005.png", "shortDesc": "dano"},
    {"id": 8008, "name": "Ritmo Letal", "iconPath": "/x/8008.png"},
    {"id": 9101, "name": "Absorver Vida", "iconPath": "/x/9101.png"},
    {"id": 9111, "name": "Triunfo", "iconPath": "/x/9111.png"},
    {"id": 9104, "name": "Lenda: Agilidade", "iconPath": "/x/9104.png"},
    {"id": 8014, "name": "Golpe de Misericórdia", "iconPath": "/x/8014.png"},
    {"id": 8017, "name": "Cortar", "iconPath": "/x/8017.png"},
    {"id": 8224, "name": "Nulificador", "iconPath": "/x/8224.png"},
    {"id": 8226, "name": "Fluxo Manaflow", "iconPath": "/x/8226.png"},
    {"id": 8210, "name": "Transcendência", "iconPath": "/x/8210.png"},
    {"id": 8234, "name": "Celeridade", "iconPath": "/x/8234.png"},
    {"id": 8214, "name": "Invocar Aery", "iconPath": "/x/8214.png"},
    {"id": 8237, "name": "Ímpeto Arcano", "iconPath": "/x/8237.png"},
    {"id": 8232, "name": "Vento Feroz", "iconPath": "/x/8232.png"},
    {"id": 5008, "name": "Adaptativo", "iconPath": "/x/5008.png"},
    {"id": 5005, "name": "Velocidade de Ataque", "iconPath": "/x/5005.png"},
    {"id": 5007, "name": "Acel. de Habilidade", "iconPath": "/x/5007.png"},
    {"id": 5010, "name": "Vel. de Movimento", "iconPath": "/x/5010.png"},
    {"id": 5001, "name": "Escalamento de Vida", "iconPath": "/x/5001.png"},
    {"id": 5011, "name": "Vida", "iconPath": "/x/5011.png"},
    {"id": 5013, "name": "Tenacidade", "iconPath": "/x/5013.png"},
]

#: As três fileiras de fragmento, como a LCU as entrega — reparar que
#: 5008 aparece nas duas primeiras e 5001 nas duas últimas.
SHARDS = [
    {"type": "kStatMod", "perks": [5008, 5005, 5007]},
    {"type": "kStatMod", "perks": [5008, 5010, 5001]},
    {"type": "kStatMod", "perks": [5011, 5013, 5001]},
]

STYLES = [
    {
        "id": 8000,
        "name": "Precisão",
        "iconPath": "/s/8000.png",
        "slots": [
            {"type": "kKeyStone", "perks": [8005, 8008]},
            {"type": "kMixedRegularSplashable", "perks": [9101, 9111]},
            {"type": "kMixedRegularSplashable", "perks": [9104]},
            {"type": "kMixedRegularSplashable", "perks": [8014, 8017]},
            *SHARDS,
        ],
    },
    {
        "id": 8200,
        "name": "Feitiçaria",
        "iconPath": "/s/8200.png",
        "slots": [
            {"type": "kKeyStone", "perks": [8214]},
            {"type": "kMixedRegularSplashable", "perks": [8224, 8226]},
            {"type": "kMixedRegularSplashable", "perks": [8210, 8234]},
            {"type": "kMixedRegularSplashable", "perks": [8237, 8232]},
            *SHARDS,
        ],
    },
]

#: Uma página de verdade: chave 8005, três da primária, duas da
#: secundária e três fragmentos.
PAGINA = (8005, 9111, 9104, 8014, 8226, 8210, 5008, 5010, 5011)


def catalog(responses=None, failures=None):
    client = FakeLcuClient(
        responses={
            endpoints.PERKS: PERKS,
            endpoints.PERK_STYLES: STYLES,
            **(responses or {}),
        },
        failures=failures,
    )
    loaded = PerkCatalog(client)
    loaded.load()
    return loaded, client


# --- a carga --------------------------------------------------------------


def test_the_catalog_learns_the_names():
    perks, _ = catalog()

    assert perks.perk(8005).name == "Ataque Certeiro"


def test_a_rune_it_never_heard_of_falls_back_to_the_id():
    """Melhor um `#404` na tela do que a tela inteira fora do ar."""
    perks, _ = catalog()

    assert perks.perk(404).name == "#404"


def test_the_rows_come_in_the_order_the_game_draws_them():
    perks, _ = catalog()

    assert perks.style(8000).rows == ((8005, 8008), (9101, 9111), (9104,), (8014, 8017))


def test_the_shards_are_kept_apart_from_the_rune_rows():
    perks, _ = catalog()

    assert perks.style(8000).shards == ((5008, 5005, 5007), (5008, 5010, 5001), (5011, 5013, 5001))


def test_a_failed_load_leaves_the_catalog_empty_not_wrong():
    perks, _ = catalog(failures={endpoints.PERKS})

    assert not perks.loaded
    assert perks.style(8000) is None


def test_the_catalog_is_only_fetched_once():
    perks, client = catalog()
    perks.load()

    assert client.paths("GET").count(endpoints.PERKS) == 1


def test_the_icon_list_has_no_repeats():
    perks, _ = catalog()

    paths = perks.icons()
    assert len(paths) == len(set(paths))
    assert "/x/8005.png" in paths and "/s/8000.png" in paths


# --- a grade --------------------------------------------------------------


def test_the_tree_marks_the_keystone():
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert tree.primary_rows[0].chosen == 8005


def test_the_tree_marks_one_rune_per_primary_row():
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert [row.chosen for row in tree.primary_rows] == [8005, 9111, 9104, 8014]


def test_the_secondary_tree_has_no_keystone_row():
    """No jogo não dá para levar a chave de outra árvore — mostrá-la
    seria oferecer o que não existe."""
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert len(tree.secondary_rows) == 3
    assert all(8214 not in [p.id for p in row.perks] for row in tree.secondary_rows)


def test_the_secondary_tree_leaves_one_row_unmarked():
    """São duas runas para três fileiras: uma fica sem marca, como no jogo."""
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert [row.chosen for row in tree.secondary_rows] == [8226, 8210, None]


def test_the_shards_land_one_per_row_even_when_the_id_repeats():
    """A armadilha: 5008 mora na primeira e na segunda fileira. Casar
    por pertencimento marcava a primeira duas vezes e deixava a segunda
    vazia — na tela, um fragmento a mais em cima e um buraco embaixo."""
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert [row.chosen for row in tree.shard_rows] == [5008, 5010, 5011]


def test_the_same_shard_twice_is_drawn_twice():
    """E quando a build de fato repete o fragmento, as duas marcas ficam."""
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, (8005, 9111, 9104, 8014, 8226, 8210, 5008, 5008, 5011))
    assert [row.chosen for row in tree.shard_rows] == [5008, 5008, 5011]


def test_the_rows_carry_the_options_that_were_not_chosen():
    """A grade mostra a árvore inteira, não só o que foi escolhido."""
    perks, _ = catalog()

    tree = perks.tree(8000, 8200, PAGINA)
    assert [p.id for p in tree.primary_rows[1].perks] == [9101, 9111]


def test_an_unknown_tree_draws_nothing():
    perks, _ = catalog()

    assert perks.tree(9999, 8200, PAGINA) is None


def test_a_page_with_no_runes_draws_nothing():
    perks, _ = catalog()

    assert perks.tree(8000, 8200, ()) is None


def test_the_runes_may_arrive_out_of_order():
    """A fonte não promete ordem nas runas comuns; a grade não depende dela."""
    perks, _ = catalog()

    baralhada = (8014, 9104, 8005, 9111, 8210, 8226, 5008, 5010, 5011)
    tree = perks.tree(8000, 8200, baralhada)
    assert [row.chosen for row in tree.primary_rows] == [8005, 9111, 9104, 8014]
