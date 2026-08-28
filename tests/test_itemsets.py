"""O arsenal que aparece na loja, dentro da partida.

O cliente guarda todos os conjuntos de itens numa lista só, e gravar
substitui a lista inteira. Quem tem conjuntos do Porofessor, do Blitz ou
feitos à mão tem tudo ali junto — então cada gravação daqui é uma chance
de apagar o trabalho de outra pessoa. É o que a maior parte destes
testes vigia.
"""

import pytest

from lolqueue.core.itemsets import ItemSets, item_set
from lolqueue.core.opgg import Block, Page
from lolqueue.lcu.client import ClientClosed

from .fakes import FakeLcuClient

SUMMONER = "/lol-summoner/v1/current-summoner"
SETS = "/lol-item-sets/v1/item-sets/42/sets"

BLOCKS = (
    Block(label="Iniciais", items=(1056, 2003, 2003), win_rate=0.5),
    Block(label="Principais", items=(3118, 3152, 4645), win_rate=0.5257),
)

#: A segunda página de um arsenal de duas abas — mesma ideia do
#: primeiro conjunto, com um item diferente escolhido no último slot.
SEGUNDA_PAGINA = (
    Block(label="Iniciais", items=(1056, 2003, 2003), win_rate=0.5),
    Block(label="Principais", items=(3089, 3152, 4645), win_rate=0.51),
)

#: O que `apply` recebe: páginas, não blocos soltos. Sem rótulo, porque
#: a maior parte destes testes vigia a gravação e não o nome da aba.
PAGINA = Page(label="", blocks=BLOCKS)
OUTRA_PAGINA = Page(label="", blocks=SEGUNDA_PAGINA)


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
        "Consumíveis",
    ]


def test_the_label_carries_the_win_rate():
    """Na loja, ver 53% é o que faz decidir entre um item e outro."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    assert conjunto["blocks"][1]["type"] == "Principais — 53% de vitórias"


def test_a_block_without_a_win_rate_keeps_a_bare_label():
    """O bloco dos situacionais junta itens de slots diferentes, cada um
    medido na sua própria amostra. Não há uma taxa que valha para o
    conjunto, e emendar a de um deles no título faria parecer que vale
    para todos — então ali a etiqueta vai limpa."""
    situacionais = Block(label="Situacionais", items=(3157, 3089), win_rate=0.0)

    conjunto = item_set(1, "Annie", (*BLOCKS, situacionais), 11)

    tipos = [b["type"] for b in conjunto["blocks"]]
    assert "Situacionais" in tipos


def test_every_set_ends_with_the_consumables():
    """Poção e sentinela não são recomendação estatística: são o que se
    repõe a cada volta à base. Por isso cabem em toda página sem que
    nada seja inventado — e por isso vêm por último, que é a ordem em
    que se compram."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    ultimo = conjunto["blocks"][-1]
    assert ultimo["type"] == "Consumíveis"
    assert [e["id"] for e in ultimo["items"]] == [
        "2003",
        "2055",
        "3340",
        "3363",
        "3364",
    ]


def test_the_abyss_does_not_sell_wards():
    """No Abismo Uivante não se coloca sentinela, e a loja de lá não
    vende nenhuma das três — só a Alteração Vidente, que existe no mapa
    12. Oferecer as outras seria mandar comprar o que não está à venda.
    """
    conjunto = item_set(1, "Annie", BLOCKS, 12)

    ultimo = conjunto["blocks"][-1]
    assert [e["id"] for e in ultimo["items"]] == ["2003", "3363"]


def test_the_three_trinkets_go_together_on_the_rift():
    """Qual totem levar depende da função, e escolher pelo jogador seria
    palpite: os três aparecem, e ele pega o que serve."""
    conjunto = item_set(1, "Annie", BLOCKS, 11)

    ids = [e["id"] for e in conjunto["blocks"][-1]["items"]]
    assert {"3340", "3363", "3364"} <= set(ids)


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


def test_the_first_page_keeps_the_plain_name():
    """A primeira página não leva número — é a de sempre."""
    conjunto = item_set(1, "Annie", BLOCKS, 11, page=0)

    assert conjunto["title"] == "LoL Queue: Annie"
    assert conjunto["uid"] == "lolqueue-1"


def test_a_later_page_gets_a_number_of_its_own():
    """Da segunda página em diante, título e `uid` se distinguem — é o
    que faz o cliente tratá-las como conjuntos separados na loja."""
    conjunto = item_set(1, "Annie", BLOCKS, 11, page=1)

    assert conjunto["title"] == "LoL Queue: Annie (2)"
    assert conjunto["uid"] == "lolqueue-1-1"


# --- a gravação -----------------------------------------------------------


def test_the_sets_the_user_already_had_survive():
    """A regra que não pode ser quebrada nunca."""
    loadout, client, _ = build([alheio("Porofessor Annie"), alheio("Meu ADC")])

    loadout.apply(1, "Annie", (PAGINA,), 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert "Porofessor Annie" in titulos
    assert "Meu ADC" in titulos


def test_the_new_set_is_added_to_the_others():
    loadout, client, _ = build([alheio("Porofessor Annie")])

    loadout.apply(1, "Annie", (PAGINA,), 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["Porofessor Annie", "LoL Queue: Annie"]


def test_our_old_sets_do_not_pile_up():
    """Cinquenta partidas não podem virar cinquenta conjuntos."""
    loadout, client, _ = build(
        [alheio("Porofessor Annie"), alheio("LoL Queue: Teemo")]
    )

    loadout.apply(1, "Annie", (PAGINA,), 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["Porofessor Annie", "LoL Queue: Annie"]


def test_several_pages_become_several_sets():
    """O pedido: mais de uma aba de arsenal, não um bloco por
    alternativa dentro de um conjunto só."""
    loadout, client, _ = build()

    loadout.apply(1, "Annie", (PAGINA, OUTRA_PAGINA), 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["LoL Queue: Annie", "LoL Queue: Annie (2)"]


def test_the_criterion_names_the_tab_in_the_shop():
    """Duas abas numeradas dizem quantas são, não o que muda entre elas.

    Com o critério no título, quem abre a loja no meio da partida lê
    "Maior taxa" e sabe por que aquela aba existe.
    """
    loadout, client, _ = build()

    loadout.apply(
        1,
        "Annie",
        (
            Page(label="Mais jogada", blocks=BLOCKS),
            Page(label="Maior taxa", blocks=SEGUNDA_PAGINA),
        ),
        11,
    )

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == [
        "LoL Queue: Annie — Mais jogada",
        "LoL Queue: Annie — Maior taxa",
    ]


def test_the_named_pages_still_get_uids_of_their_own():
    """O nome distingue para o jogador; o `uid` distingue para o cliente.
    Sem isso a segunda aba sobrescreveria a primeira."""
    loadout, client, _ = build()

    loadout.apply(
        1,
        "Annie",
        (
            Page(label="Mais jogada", blocks=BLOCKS),
            Page(label="Maior taxa", blocks=SEGUNDA_PAGINA),
        ),
        11,
    )

    uids = [s["uid"] for s in written(client)["itemSets"]]
    assert uids == ["lolqueue-1", "lolqueue-1-1"]


def test_our_old_pages_do_not_pile_up_either():
    """Um arsenal de três páginas de uma partida anterior não pode
    deixar sobra quando a atual só tem uma."""
    loadout, client, _ = build(
        [
            alheio("Porofessor Annie"),
            {"title": "LoL Queue: Teemo", "blocks": [], "uid": "lolqueue-1"},
            {"title": "LoL Queue: Teemo (2)", "blocks": [], "uid": "lolqueue-1-1"},
            {"title": "LoL Queue: Teemo (3)", "blocks": [], "uid": "lolqueue-1-2"},
        ]
    )

    loadout.apply(1, "Annie", (PAGINA,), 11)

    titulos = [s["title"] for s in written(client)["itemSets"]]
    assert titulos == ["Porofessor Annie", "LoL Queue: Annie"]


def test_the_rest_of_the_payload_is_given_back_untouched():
    """`accountId` e companhia voltam como vieram: não são nossos."""
    loadout, client, _ = build()

    loadout.apply(1, "Annie", (PAGINA,), 11)

    assert written(client)["accountId"] == 7


def test_without_blocks_nothing_is_written():
    """Sem dados do OP.GG, a lista do usuário não é nem lida."""
    loadout, client, _ = build([alheio("Porofessor Annie")])

    loadout.apply(1, "Annie", (), 11)

    assert SETS not in client.paths("PUT")


def test_the_journal_says_what_happened():
    loadout, _, messages = build()

    loadout.apply(1, "Annie", (PAGINA,), 11)

    assert any("Annie" in message for message in messages)


# --- quando dá errado -----------------------------------------------------


def test_a_failed_read_writes_nothing():
    """Sem saber o que já existe, gravar seria apagar às cegas."""
    loadout, client, _ = build([alheio("Porofessor Annie")], failures={SETS})

    loadout.apply(1, "Annie", (PAGINA,), 11)

    assert SETS not in client.paths("PUT")


def test_a_failure_does_not_escape():
    """Quem chama está no meio de escolher campeão."""
    loadout, _, messages = build(failures={SUMMONER})

    loadout.apply(1, "Annie", (PAGINA,), 11)

    assert any("arsenal" in message for message in messages)


def test_a_closed_client_escapes_on_purpose():
    """A única falha que sobe: sem cliente não há loja a montar, e quem
    espera por esta exceção é o watcher, para reconectar. Engolida, ela
    viraria um erro de arsenal que não explica nada."""
    loadout, client, messages = build()
    client.closed = True

    with pytest.raises(ClientClosed):
        loadout.apply(1, "Annie", (PAGINA,), 11)
    assert messages == []


def test_a_broken_list_is_left_alone():
    """Resposta fora do formato esperado: melhor não escrever nada."""
    loadout, client, _ = build()
    client.responses[SETS] = {"itemSets": "isso não é uma lista"}

    loadout.apply(1, "Annie", (PAGINA,), 11)

    assert SETS not in client.paths("PUT")


def test_the_summoner_is_asked_only_once():
    """O id não muda enquanto o cliente estiver aberto."""
    loadout, client, _ = build()

    loadout.apply(1, "Annie", (PAGINA,), 11)
    loadout.apply(2, "Olaf", (PAGINA,), 11)

    assert client.paths("GET").count(SUMMONER) == 1


def test_a_thin_sample_says_so_instead_of_showing_a_rate():
    """Três partidas não são conselho, e o rótulo não pode fingir que são.

    Aconteceu de verdade: com o elo em Challenger, o Kog'Maw tinha três
    partidas no bloco principal e a loja anunciava "33% de vitórias" —
    número que só existe porque uma das três foi derrota. Estampar taxa
    de amostra dessa altura é pior que não estampar nada: quem lê acha
    que a build é ruim, quando o que é ruim é a medição.
    """
    magros = (Block(label="Principais", items=(3089,), win_rate=0.333, games=3),)

    conjunto = item_set(1, "Kog'Maw", magros, 11)

    assert conjunto["blocks"][0]["type"] == "Principais — amostra pequena (3 partidas)"


def test_a_solid_sample_shows_the_rate_with_the_sample_size():
    """Com amostra que sustenta, a taxa vem acompanhada de quantas partidas."""
    firmes = (Block(label="Principais", items=(3089,), win_rate=0.59, games=445),)

    conjunto = item_set(1, "Kog'Maw", firmes, 11)

    assert conjunto["blocks"][0]["type"] == "Principais — 59% em 445 partidas"
