"""Runas e feitiços vindos do OP.GG.

A recomendação da Riot é curadoria; a do OP.GG é o que mais venceu em
partidas de verdade. O que chega pelo servidor MCP oficial não é JSON:
é um formato compacto, feito para LLM, que declara o esquema em cima e
despeja os valores por posição embaixo. O parser lê o esquema em vez de
contar vírgulas — se o OP.GG acrescentar um campo no meio, nada
desanda.

A resposta em RESPOSTA foi capturada do servidor real (Annie, meio).
"""

from lolqueue.core.opgg import Build, OpggSource, parse_build

RESPOSTA = (
    "class LolGetChampionAnalysis: data\n"
    "class Data: summoner_spells,runes\n"
    "class SummonerSpells: ids,ids_names,win,play,pick_rate\n"
    "class Runes: id,primary_page_id,primary_page_name,primary_rune_ids,"
    "primary_rune_names,secondary_page_id,secondary_page_name,"
    "secondary_rune_ids,secondary_rune_names,stat_mod_ids,stat_mod_names,"
    "play,win,pick_rate\n"
    "\n"
    "LolGetChampionAnalysis(Data(SummonerSpells([4,14],[4,14],8375,16173,0.75),"
    'Runes(8112,8100,"Domination",[8112,8126,8140,8105],'
    '["Electrocute","Cheap Shot","Grisly Mementos","Relentless Hunter"],'
    '8200,"Sorcery",[8224,8233],["Axiom Arcanist","Absolute Focus"],'
    "[5008,5008,5001],[5008,5008,5001],9850,5007,0.45)))"
)

#: Captura do servidor real pedindo tudo o que o app usa (Annie,
#: meio, Diamante+). Repare em `summoner_spells` chegando como
#: `CoreItems`: o servidor reaproveita a etiqueta para qualquer
#: coisa de mesma forma, e é por isso que o parser se guia pelo
#: esquema de `Data`, nunca pelo nome da classe.
COMPLETA = (
    "class LolGetChampionAnalysis: data\n"
    "class Data: core_items,boots,starter_items,fourth_items,"
    "fifth_items,sixth_items,summoner_spells,runes\n"
    "class CoreItems: ids,ids_names,play,win,pick_rate\n"
    "class Runes: id,primary_page_id,primary_page_name,primary_rune_ids,"
    "primary_rune_names,secondary_page_id,secondary_page_name,"
    "secondary_rune_ids,secondary_rune_names,stat_mod_ids,stat_mod_names,"
    "play,win,pick_rate\n"
    "\n"
    "LolGetChampionAnalysis(Data("
    'CoreItems([3118,3152,4645],["Malignance","Hextech Rocketbelt",'
    '"Shadowflame"],816,429,0.16),'
    'CoreItems([3020],["Sorcerer\'s Shoes"],6131,3145,0.71),'
    'CoreItems([1056,2003,2003],["Doran\'s Ring","Health Potion",'
    '"Health Potion"],8599,4320,0.97),'
    '[CoreItems([3157],["Zhonya\'s Hourglass"],465,280,0.24),'
    'CoreItems([3089],["Rabadon\'s Deathcap"],438,256,0.23),'
    'CoreItems([3135],["Void Staff"],253,137,0.13)],'
    '[CoreItems([3089],["Rabadon\'s Deathcap"],98,53,0.24),'
    'CoreItems([3157],["Zhonya\'s Hourglass"],80,39,0.19),'
    'CoreItems([3135],["Void Staff"],68,41,0.16)],'
    '[CoreItems([4646],["Stormsurge"],2,0,0.25),'
    'CoreItems([3157],["Zhonya\'s Hourglass"],2,1,0.25),'
    'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)],'
    "CoreItems([4,14],[4,14],6384,3240,0.7),"
    'Runes(8112,8100,"Domination",[8112,8126,8140,8105],'
    '["Electrocute","Cheap Shot","Grisly Mementos","Relentless Hunter"],'
    '8200,"Sorcery",[8224,8233],["Axiom Arcanist","Absolute Focus"],'
    "[5008,5008,5001],[5008,5008,5001],3212,1585,0.36)))"
)

DIAGNOSTICO = (
    "class LolGetChampionAnalysis: _field_diagnostics\n"
    "class FieldDiagnostics: unmatched_fields,hint\n"
    "\n"
    'LolGetChampionAnalysis(FieldDiagnostics(["runes"],"These field names did not match"))'
)


# --- o parser ------------------------------------------------------------


def test_it_reads_the_nine_perks_in_the_order_the_client_wants():
    """Quatro da árvore principal, duas da secundária, três fragmentos."""
    build = parse_build(RESPOSTA)

    assert build.perks == (8112, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001)


def test_it_reads_both_trees():
    build = parse_build(RESPOSTA)

    assert (build.style, build.sub_style) == (8100, 8200)


def test_it_reads_the_summoner_spells():
    build = parse_build(RESPOSTA)

    assert build.spells == (4, 14)


def test_a_field_added_in_the_middle_does_not_shift_everything():
    """O esquema vem junto da resposta; é ele que manda, não a posição."""
    texto = RESPOSTA.replace(
        "class Runes: id,primary_page_id",
        "class Runes: id,novidade,primary_page_id",
    ).replace("Runes(8112,8100,", 'Runes(8112,"nao me atrapalhe",8100,')

    build = parse_build(texto)

    assert build.style == 8100
    assert build.perks[0] == 8112


def test_a_comma_inside_a_name_does_not_split_a_field():
    texto = RESPOSTA.replace('"Domination"', '"Domination, a arvore"')

    assert parse_build(texto).style == 8100


def test_an_empty_answer_gives_nothing():
    assert parse_build("") is None


def test_the_diagnostics_answer_gives_nothing():
    """Campo pedido errado devolve explicação, não dados."""
    assert parse_build(DIAGNOSTICO) is None


def test_an_incomplete_page_is_refused():
    """Meia runa é pior que runa nenhuma: some com o resto da página."""
    texto = RESPOSTA.replace("[8112,8126,8140,8105]", "[8112,8126]")

    assert parse_build(texto) is None


def test_junk_where_a_number_should_be_gives_nothing():
    texto = RESPOSTA.replace("[5008,5008,5001]", '["sei la","o que","é isso"]', 1)

    assert parse_build(texto) is None


def test_a_truncated_answer_gives_nothing():
    """Resposta cortada no meio não vira página pela metade."""
    assert parse_build(RESPOSTA[: len(RESPOSTA) - 40]) is None


def test_the_first_page_is_the_one_that_counts():
    """Havendo mais de uma página, elas vêm em lista.

    É como o servidor manda toda multiplicidade — foi assim que os
    itens de 4º, 5º e 6º slot chegaram na captura real. A ordem é da
    mais jogada para a menos, então a primeira é a resposta.
    """
    segunda = 'Runes(9999,8300,"Inspiration",[8351,8306,8304,8321],[],'
    segunda += '8000,"Precision",[9111,8014],[],[5005,5008,5001],[],1,1,0.1)'
    texto = RESPOSTA.replace("Runes(8112,", "[Runes(8112,").replace(
        "0.45)))", "0.45)," + segunda + "]))"
    )

    assert parse_build(texto).style == 8100


def test_a_value_too_many_is_refused():
    """Se a contagem não bate com o esquema, ninguém sabe qual
    valor é qual. Chutar aí sairia caro: viraria runa errada.
    """
    texto = RESPOSTA.replace(
        "class Data: summoner_spells,runes", "class Data: runes"
    )

    assert parse_build(texto) is None


# --- itens ---------------------------------------------------------------


def test_the_spells_are_read_even_wearing_another_label():
    """Pedindo tudo, os feitiços chegam como `CoreItems`.

    Foi o que quase passou despercebido: o parser procurava a
    etiqueta `SummonerSpells`, que some quando o pedido cresce. Ler
    pelo esquema de `Data` é o que torna isso irrelevante.
    """
    assert parse_build(COMPLETA).spells == (4, 14)


def test_the_runes_survive_the_bigger_answer():
    build = parse_build(COMPLETA)

    assert build.style == 8100
    assert build.perks[0] == 8112


def test_the_blocks_come_in_the_order_you_buy_them():
    """Iniciais primeiro, botas, principais, depois as opções."""
    blocks = parse_build(COMPLETA).blocks

    assert [b.label for b in blocks] == [
        "Iniciais",
        "Botas",
        "Principais",
        "4º item",
        "5º item",
        "6º item",
    ]


def test_the_starting_items_keep_the_repeated_potion():
    """Duas poções são duas poções, não uma."""
    blocks = {b.label: b for b in parse_build(COMPLETA).blocks}

    assert blocks["Iniciais"].items == (1056, 2003, 2003)


def test_the_core_is_the_trio_that_wins():
    blocks = {b.label: b for b in parse_build(COMPLETA).blocks}

    assert blocks["Principais"].items == (3118, 3152, 4645)
    assert blocks["Botas"].items == (3020,)


def test_the_late_slots_gather_every_option():
    """Cada opção vem num `CoreItems` próprio; o bloco junta os três.
    """
    blocks = {b.label: b for b in parse_build(COMPLETA).blocks}

    assert blocks["4º item"].items == (3157, 3089, 3135)
    assert blocks["6º item"].items == (4646, 3157, 3102)


def test_the_core_block_carries_its_win_rate():
    """429 vitórias em 816 partidas — o que decide a compra."""
    blocks = {b.label: b for b in parse_build(COMPLETA).blocks}

    assert round(blocks["Principais"].win_rate, 3) == 0.526


def test_an_empty_slot_becomes_no_block():
    """Campeão sem 6º item não ganha um bloco vazio na loja."""
    texto = COMPLETA.replace(
        '[CoreItems([4646],["Stormsurge"],2,0,0.25),'
        'CoreItems([3157],["Zhonya\'s Hourglass"],2,1,0.25),'
        'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
        "[]",
    )

    labels = [b.label for b in parse_build(texto).blocks]

    assert "6º item" not in labels
    assert "5º item" in labels


def test_an_answer_without_items_still_gives_the_runes():
    """Runa e item são independentes: um faltar não leva o outro.
    """
    build = parse_build(RESPOSTA)

    assert build.blocks == ()
    assert build.perks[0] == 8112


# --- a fonte -------------------------------------------------------------


class FakeSend:
    """Substitui a ida à rede, guardando o que foi pedido."""

    def __init__(self, answer=RESPOSTA, fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        if self.fail:
            raise OSError("sem rede")
        return self.answer


def test_it_asks_for_the_champion_and_the_lane():
    send = FakeSend()

    OpggSource(send=send).fetch("Annie", "middle", aram=False)

    assert send.calls[0]["champion"] == "Annie"
    assert send.calls[0]["position"] == "MID"


def test_it_translates_every_lane_the_client_uses():
    send = FakeSend()
    source = OpggSource(send=send)

    for position in ("top", "jungle", "middle", "bottom", "utility"):
        source.fetch("Annie", position, aram=False)

    assert [c["position"] for c in send.calls] == [
        "TOP",
        "JUNGLE",
        "MID",
        "ADC",
        "SUPPORT",
    ]


def test_it_asks_the_elo_that_was_chosen():
    send = FakeSend()

    OpggSource(send=send).fetch("Annie", "middle", aram=False)

    assert send.calls[0]["tier"] == "diamond_plus"


def test_the_howling_abyss_asks_for_aram():
    """Feitiço e runa de ARAM não são os da Fenda."""
    send = FakeSend()

    OpggSource(send=send).fetch("Annie", "middle", aram=True)

    assert send.calls[0]["game_mode"] == "ARAM"


def test_without_a_lane_the_rift_is_not_even_asked():
    """Na Fenda a rota é tudo: a runa de caçador não serve na asa.

    O OP.GG exige a posição, e no modo cego o cliente não atribui
    nenhuma. Chutar uma rota seria pior que devolver a pergunta.
    """
    send = FakeSend()

    assert OpggSource(send=send).fetch("Annie", None, aram=False) is None
    assert send.calls == []


def test_the_abyss_needs_no_lane():
    """No ARAM ninguém tem rota, e o OP.GG responde o mesmo para
    todas elas — verificado contra o servidor. Sem isso o modo
    inteiro ficaria de fora.
    """
    send = FakeSend()

    build = OpggSource(send=send).fetch("Annie", None, aram=True)

    assert build is not None
    assert send.calls[0]["game_mode"] == "ARAM"


def test_the_abyss_asks_once_no_matter_the_lane():
    send = FakeSend()
    source = OpggSource(send=send)

    source.fetch("Annie", "middle", aram=True)
    source.fetch("Annie", "utility", aram=True)
    source.fetch("Annie", None, aram=True)

    assert len(send.calls) == 1


def test_the_answer_becomes_a_build():
    build = OpggSource(send=FakeSend()).fetch("Annie", "middle", aram=False)

    assert build == Build(
        style=8100,
        sub_style=8200,
        perks=(8112, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001),
        spells=(4, 14),
    )


def test_a_network_failure_is_not_an_explosion():
    """Sem OP.GG o app cai na Riot — quem chama não pode ter que se defender."""
    assert OpggSource(send=FakeSend(fail=True)).fetch("Annie", "middle", aram=False) is None


def test_the_same_champion_is_only_asked_once():
    send = FakeSend()
    source = OpggSource(send=send)

    source.fetch("Annie", "middle", aram=False)
    source.fetch("Annie", "middle", aram=False)

    assert len(send.calls) == 1


def test_another_lane_is_another_question():
    send = FakeSend()
    source = OpggSource(send=send)

    source.fetch("Annie", "middle", aram=False)
    source.fetch("Annie", "utility", aram=False)

    assert len(send.calls) == 2


def test_a_failure_is_not_cached():
    """Insistir depois faz sentido: a rede volta."""
    send = FakeSend(fail=True)
    source = OpggSource(send=send)

    source.fetch("Annie", "middle", aram=False)
    source.fetch("Annie", "middle", aram=False)

    assert len(send.calls) == 2
