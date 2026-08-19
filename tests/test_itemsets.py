"""O arsenal que aparece na loja, dentro da partida.

O cliente guarda todos os conjuntos de itens numa lista só, e gravar
substitui a lista inteira. Quem tem conjuntos do Porofessor, do Blitz ou
feitos à mão tem tudo ali junto — então cada gravação daqui é uma chance
de apagar o trabalho de outra pessoa. É o que a maior parte destes
testes vigia.
"""

from lolqueue.core.itemsets import ItemSets, item_set
from lolqueue.core.opgg import Block

from .fakes import FakeLcuClient

SUMMONER = "/lol-summoner/v1/current-summoner"
SETS = "/lol-item-sets/v1/item-sets/42/sets"

BLOCKS = (
    Block(label="Iniciais", items=(1056, 2003, 2003), win_rate=0.5),
    Block(label="Principais", items=(3118, 3152, 4645), win_rate=0.5257),
)


def alheio(title):
    """Um conjunto como os que o usuário já tem guardados."""
    return {"title": title, "blocks": [], "uid": f"uid-{title}"}


def build(existing=(), failures=None):
    client = FakeLcuClient(
        responses={
            SUMMONER: {"summonerId": 42},
            SETS: {"accountId": 7, "itemSets": list(existing), "timestamp": 0},
        },
        failures=failures,
    )
    messages = []
    return ItemSets(client, log=messages.append), client, messages


def written(client):
    """O corpo do último PUT em conjuntos de itens."""
    return [body for path, body in client.payloads if path == SETS][-1]


# --- a montagem -----------------------------------------------------------


def test_the_set_is_named_after_the_champion():
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert conjunto["title"] == "LoL Queue: Annie"


def test_the_set_belongs_to_the_champion_and_the_map():
    """Assim ele não polui a loja de todos os outros campeões."""
    conjunto = item_set(1, "Annie", BLOCKS, 12)

    assert conjunto["associatedChampions"] == [1]
    assert conjunto["associatedMaps"] == [12]


def test_the_blocks_keep_the_order_they_came_in():
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert [b["type"].split(" —")[0] for b in conjunto["blocks"]] == [
        "Iniciais",
        "Principais",
    ]


def test_the_label_carries_the_win_rate():
    """Na loja, ver 53% é o que faz decidir entre um item e outro."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert conjunto["blocks"][1]["type"] == "Principais — 53% de vitórias"


def test_the_item_ids_go_as_text():
    """O cliente recusa a lista inteira se um id vier como número."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert conjunto["blocks"][1]["items"] == [
        {"count": 1, "id": "3118"},
        {"count": 1, "id": "3152"},
        {"count": 1, "id": "4645"},
    ]


def test_the_repeated_potion_becomes_a_count():
    """Duas poções são uma linha com “x2”, não duas linhas iguais."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert conjunto["blocks"][0]["items"] == [
        {"count": 1, "id": "1056"},
        {"count": 2, "id": "2003"},
    ]


# --- a gravação -----------------------------------------------------------


def test_the_sets_the_user_already_had_survive():
    """A regra que não pode ser quebrada nunca."""
    loadout, client, _ = build([alheio("Porofessor Annie"), alheio("Meu ADC")])

    loadout.apply(1, "Annie", BLOCKS, 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert "Porofessor Annie" in titulos
    assert "Meu ADC" in titulos


def test_the_new_set_is_added_to_the_others():
    loadout, client, _ = build([alheio("Porofessor Annie")])

    loadout.apply(1, "Annie", BLOCKS, 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["Porofessor Annie", "LoL Queue: Annie"]


def test_our_old_sets_do_not_pile_up():
    """Cinquenta partidas não podem virar cinquenta conjuntos."""
    loadout, client, _ = build(
        [alheio("Porofessor Annie"), alheio("LoL Queue: Teemo")]
    )

    loadout.apply(1, "Annie", BLOCKS, 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["Porofessor Annie", "LoL Queue: Annie"]


def test_the_rest_of_the_payload_is_given_back_untouched():
    """`accountId` e companhia voltam como vieram: não são nossos."""
    loadout, client, _ = build()

    loadout.apply(1, "Annie", BLOCKS, 11)

    assert written(client)["accountId"] == 7


def test_without_blocks_nothing_is_written():
    """Sem dados do OP.GG, a lista do usuário não é nem lida."""
    loadout, client, _ = build([alheio("Porofessor Annie")])

    loadout.apply(1, "Annie", (), 11)

    assert SETS not in client.paths("PUT")


def test_the_journal_says_what_happened():
    loadout, _, messages = build()

    loadout.apply(1, "Annie", BLOCKS, 11)

    assert any("Annie" in message for message in messages)


# --- quando dá errado -----------------------------------------------------


def test_a_failed_read_writes_nothing():
    """Sem saber o que já existe, gravar seria apagar às cegas."""
    loadout, client, _ = build([alheio("Porofessor Annie")], failures={SETS})

    loadout.apply(1, "Annie", BLOCKS, 11)

    assert SETS not in client.paths("PUT")


def test_a_failure_does_not_escape():
    """Quem chama está no meio de escolher campeão."""
    loadout, _, messages = build(failures={SUMMONER})

    loadout.apply(1, "Annie", BLOCKS, 11)

    assert any("arsenal" in message for message in messages)


def test_a_broken_list_is_left_alone():
    """Resposta fora do formato esperado: melhor não escrever nada."""
    loadout, client, _ = build()
    client.responses[SETS] = {"itemSets": "isso não é uma lista"}

    loadout.apply(1, "Annie", BLOCKS, 11)

    assert SETS not in client.paths("PUT")


def test_the_summoner_is_asked_only_once():
    """O id não muda enquanto o cliente estiver aberto."""
    loadout, client, _ = build()

    loadout.apply(1, "Annie", BLOCKS, 11)
    loadout.apply(2, "Olaf", BLOCKS, 11)

    assert client.paths("GET").count(SUMMONER) == 1
