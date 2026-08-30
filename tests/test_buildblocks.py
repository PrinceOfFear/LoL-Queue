"""O degrau da lista de compra, visto sozinho.

As regras deste módulo chegam à loja pelos dois lados da recomendação —
o boletim do campeão (`opgg`) e o guia do confronto (`matchup`) —, e lá
elas aparecem misturadas ao parser. Aqui aparecem cruas: cada teste
descreve um estrago que já foi visto na tela do jogador.
"""

from lolqueue.core.buildblocks import (
    CONSUMABLES,
    EARLY_ONLY,
    MIN_FALLBACK_PLAYS,
    Block,
    extras,
    slot,
    taken,
)


def bloco(items, win_rate=0.55, games=400, pick_rate=0.30, label="x"):
    return Block(
        label=label,
        items=tuple(items),
        win_rate=win_rate,
        games=games,
        pick_rate=pick_rate,
    )


# --- o degrau ------------------------------------------------------------


def test_a_step_shows_the_leader_and_its_alternatives():
    """Um item por degrau fazia a ordem de compra parecer obrigatória."""
    comprados = set()

    saida = slot(
        [bloco([3157]), bloco([3089], win_rate=0.54), bloco([3135], win_rate=0.53)],
        comprados,
    )

    assert saida.items == (3157, 3089, 3135)


def test_only_the_recommended_item_is_reserved():
    """As alternativas ficam livres para reaparecer no degrau seguinte —
    é isso que as torna alternativas.

    Reservando as três, o degrau seguinte sumia inteiro: o 4º item da
    Ahri levava Zhonya's, Rabadon's e Void Staff, e o 5º ficava sem
    nenhuma opção para oferecer.
    """
    comprados = set()

    slot([bloco([3157]), bloco([3089], win_rate=0.54)], comprados)

    assert comprados == {3157}


def test_a_consumable_never_takes_up_a_slot():
    """Poção se recompra a cada volta à base, e por isso não reserva vaga.

    A regra antiga era mais grossa: os degraus de iniciais e botas
    ficavam *inteiros* fora do controle de repetidos, e o efeito
    colateral era o item inicial permanente reaparecer no núcleo — a
    Lágrima da Deusa do Nautilus saía em "Iniciais" e de novo em
    "Principais", mandando comprar duas.
    """
    comprados = set()

    slot([bloco([3070, 2003, 2003], label="Iniciais")], comprados)

    assert 2003 not in comprados  # poção
    assert 3070 in comprados  # Lágrima, que é permanente
    assert 2003 in CONSUMABLES


def test_an_item_already_bought_does_not_come_back():
    comprados = {3157}

    saida = slot([bloco([3157]), bloco([3089], win_rate=0.54)], comprados)

    assert saida.items == (3089,)


def test_a_step_with_nothing_left_to_offer_just_drops():
    """Bloco vazio na loja é pior que um degrau a menos."""
    assert slot([bloco([3157])], {3157}) is None
    assert slot([], set()) is None


# --- o piso da repescagem ------------------------------------------------


def test_a_weak_sample_still_shows_the_most_played():
    """Ninguém acima dos pisos de `ranking`, mas amostra que sustenta a
    leitura de popularidade: o degrau repete o mais jogado."""
    saida = slot(
        [bloco([4646], win_rate=0.37, games=19, pick_rate=0.25)],
        set(),
    )

    assert saida.items == (4646,)


def test_a_handful_of_games_is_not_a_recommendation():
    """O 6º item da Ashe no Desafiante saía Cimitarra Mercurial com 2
    partidas e 0 vitórias; o da Ahri, Chama Sombria com 1. Os dois
    entravam na loja com a mesma cara do item de mil partidas."""
    assert MIN_FALLBACK_PLAYS == 10
    assert slot([bloco([4646], win_rate=0.0, games=2, pick_rate=0.25)], set()) is None


# --- os situacionais -----------------------------------------------------


def test_the_extras_take_one_item_per_alternative():
    """Não há ordem de compra a comunicar aqui, só opções: o bloco vem
    do ranking dos mais construídos, não de um degrau."""
    saida = extras(
        [bloco([3157, 3089]), bloco([3135], win_rate=0.54)],
        set(),
        "Situacionais",
    )

    assert saida.items == (3157, 3135)
    assert saida.label == "Situacionais"


def test_the_extras_skip_what_the_build_already_bought():
    """Alternativa repetida não oferece situação nenhuma: só ocupa a
    linha que o item novo ocuparia."""
    saida = extras([bloco([3157]), bloco([3135], win_rate=0.54)], {3157}, "S")

    assert saida.items == (3135,)


def test_the_extras_reserve_what_they_show():
    comprados = {3157}

    extras([bloco([3135])], comprados, "S")

    assert comprados == {3157, 3135}


def test_a_starting_item_is_never_a_situational_pick():
    """O ranking dos mais construídos é liderado pelo que se compra aos
    quatro minutos: na Ahri de Mestre+ o bloco saía `(Bastão Rúnico,
    Lacre Sombrio)` — 350 de ouro como saída para o fim de jogo."""
    saida = extras([bloco([1082]), bloco([3135], win_rate=0.54)], set(), "S")

    assert saida.items == (3135,)
    assert 1082 in EARLY_ONLY  # Lacre Sombrio


def test_the_support_quest_items_are_not_a_starting_item():
    """Escolher entre eles é decisão de verdade, e é a única decisão de
    compra que sobra para um suporte no fim da partida."""
    assert 3865 in EARLY_ONLY  # Atlas do Mundo, a primeira pedra
    assert 3876 not in EARLY_ONLY  # Trenó do Solstício, o item completo
    assert 3869 not in EARLY_ONLY  # Oposição Celestial


def test_an_extras_block_with_nothing_new_just_drops():
    assert extras([bloco([3157])], {3157}, "S") is None
    assert extras([], set(), "S") is None


def test_a_low_sample_extra_never_shows_up():
    assert extras([bloco([3135], win_rate=0.0, games=3)], set(), "S") is None


# --- o que já saiu -------------------------------------------------------


def test_taken_collects_every_item_on_screen():
    """O filtro dos situacionais é contra **tudo o que está na tela**,
    não só contra as compras recomendadas: as alternativas dos degraus
    anteriores também já estão à vista."""
    assert taken([bloco([3157, 3089]), bloco([3135])]) == {3157, 3089, 3135}
