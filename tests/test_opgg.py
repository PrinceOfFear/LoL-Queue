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


def blocos(texto, indice=0):
    """Os blocos de uma página, por rótulo."""
    return {b.label: b for b in parse_build(texto).pages[indice].blocks}


def degrau(texto, label, indice=0):
    """Os itens de um degrau da lista de compra, alternativas inclusas."""
    bloco = blocos(texto, indice).get(label)
    return bloco.items if bloco is not None else ()


def todos_os_itens(texto):
    """Tudo o que o arsenal manda comprar, em qualquer bloco."""
    return {
        item
        for page in parse_build(texto).pages
        for bloco in page.blocks
        for item in bloco.items
    }


#: Os degraus que a `COMPLETA` produz. Não tem 6º item de propósito: o
#: 6º slot dessa captura mede duas partidas, e amostra dessa altura não
#: chega à loja (veja o teste do piso logo abaixo).
DEGRAUS = ["Iniciais", "Botas", "Principais", "4º item", "5º item"]

#: A lista inteira, para as capturas cujo 6º slot tem amostra.
DEGRAUS_COM_SEXTO = DEGRAUS + ["6º item"]


def test_each_step_of_the_purchase_gets_its_own_title():
    """Cada degrau é um título na loja, na ordem em que se compra."""
    primeira = parse_build(COMPLETA).pages[0].blocks

    assert [b.label for b in primeira] == DEGRAUS


def test_a_slot_measured_on_a_handful_of_games_never_reaches_the_shop():
    """O 6º slot da captura real mede 2, 2 e 1 partidas.

    Era mostrado como qualquer outro degrau — mesma tipografia, mesma
    cara de recomendação — e o jogador não tinha como saber que aquilo
    era ruído. Agora o degrau some, e a lista de compra encurta.
    """
    assert "6º item" not in blocos(COMPLETA)
    assert 4646 not in todos_os_itens(COMPLETA)  # Stormsurge, 2 partidas


def test_a_step_shows_the_alternatives_side_by_side():
    """A queixa que motivou o formato: o app não dava variação nenhuma.

    Havia um item por degrau — o mais jogado — e o jogador via uma
    ordem de compra fixa, como se não houvesse decisão a tomar. Agora o
    degrau mostra o recomendado e as saídas medidas, que é o que os
    apps do gênero põem lado a lado.
    """
    assert degrau(COMPLETA, "4º item") == (3157, 3089, 3135)


def test_the_arsenal_is_a_single_page():
    """As abas por critério viraram alternativas dentro do bloco.

    Havia duas páginas, "Mais jogada" e "Maior taxa", e a escolha entre
    elas acontecia antes de abrir a loja — trocar de aba no meio da
    partida ninguém troca. As duas leituras agora convivem no mesmo
    degrau, uma ao lado da outra.
    """
    pages = parse_build(COMPLETA).pages

    assert len(pages) == 1
    assert pages[0].label == ""


def test_the_client_also_gets_statistical_build_paths():
    """As medições viram abas separadas além da recomendação principal.

    O OP.GG não publica uma etiqueta proprietária de ``AP``/``AD`` por
    caminho; as abas usam somente critérios que a resposta realmente traz.
    """
    build = parse_build(COMPLETA)

    assert [page.label for page in build.variant_pages] == [
        "Mais jogada",
        "Maior taxa",
        "Alternativa validada",
    ]
    for page in build.variant_pages:
        assert {block.label for block in page.blocks} >= {
            "Iniciais",
            "Botas",
            "Principais",
        }


def test_alternative_path_changes_only_measured_steps():
    build = parse_build(COMPLETA)
    alternative = next(
        page for page in build.variant_pages if page.label == "Alternativa validada"
    )

    assert dict((block.label, block.items) for block in alternative.blocks)["4º item"] == (
        3089,
    )
    assert dict((block.label, block.items) for block in alternative.blocks)["5º item"] == (
        3157,
    )


def test_the_two_readings_share_the_same_step():
    """Void Staff venceu 60% em 68 partidas; Rabadon's, 54% em 98.

    Quem quer o mais seguro compra Rabadon's; quem quer a taxa compra
    Void Staff. Antes cada um vivia numa aba, e só uma delas era aberta.
    """
    quarto = degrau(COMPLETA, "4º item")

    assert 3089 in quarto  # Rabadon's, o mais jogado
    assert 3135 in quarto  # Void Staff, a maior taxa


def test_the_recommended_buy_never_repeats_between_steps():
    """O primeiro item de cada degrau é a compra recomendada.

    Repeti-la no degrau seguinte seria mandar comprar duas vezes o
    mesmo lendário — o jogo não permite, e a loja mostraria os dois.
    """
    lideres = [b.items[0] for b in parse_build(COMPLETA).pages[0].blocks]

    assert len(lideres) == len(set(lideres))


def test_a_single_game_at_a_hundred_percent_never_shows_up():
    """Banshee's Veil: uma partida, uma vitória, 100%.

    Encabeçava o 6º item e ia para a primeira página. Não entra nem na
    página da maior taxa: o piso de amostra de `ranking` corta quem não
    jogou o bastante,
    e uma partida não mede nada. Some do arsenal, que é o que dado
    nenhum merece — aparecer é que seria inventar conselho.
    """
    assert 3102 not in todos_os_itens(COMPLETA)


#: Um 6º slot onde as duas leituras discordariam se não houvesse piso:
#: Stormsurge é disparado o mais jogado, e Banshee's ganhou a única
#: partida que jogou. Nenhum dos dois chega perto do piso de amostra.
SEXTO_SEM_AMOSTRA = COMPLETA.replace(
    '[CoreItems([4646],["Stormsurge"],2,0,0.25),'
    'CoreItems([3157],["Zhonya\'s Hourglass"],2,1,0.25),'
    'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
    '[CoreItems([4646],["Stormsurge"],19,7,0.25),'
    'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
)


def test_a_slot_without_a_solid_sample_falls_back_to_the_most_played():
    """Sem ninguém acima dos pisos de `ranking`, o degrau não elege um
    campeão de amostra minúscula só para ter o que mostrar.

    Ele repete o mais jogado — a única das duas medidas que uma amostra
    dessas ainda sustenta — e nada mais.
    """
    # Banshee's venceu 100% da única partida, e não entra.
    assert degrau(SEXTO_SEM_AMOSTRA, "6º item") == (4646,)  # Stormsurge


#: O 4º slot da `COMPLETA` com um item de amostra folgada e taxa
#: absurda: Mejai's Soulstealer a 83% em 107 partidas, escolhido em 2%
#: do slot. Não é hipótese — é o que o OP.GG devolve para a Ahri do
#: meio, e é o conselho mais perigoso que a fonte produz, porque a
#: amostra passa em qualquer filtro que só olhe tamanho.
QUARTO_COM_MEJAIS = COMPLETA.replace(
    'CoreItems([3135],["Void Staff"],253,137,0.13)],',
    'CoreItems([3135],["Void Staff"],253,137,0.13),'
    'CoreItems([3041],["Mejai\'s Soulstealer"],107,89,0.02)],',
)


def test_an_item_only_bought_when_already_ahead_never_reaches_the_shop():
    """Mejai's é item que se compra *porque* a partida já está ganha.

    As 107 partidas não são amostra da população: são amostra de quem
    estava na frente. A taxa de 83% mede o estado do jogo no momento da
    compra, não o efeito do item — e contra isso amostra grande não
    protege, só o piso de frequência de escolha protege.
    """
    assert 3041 not in todos_os_itens(QUARTO_COM_MEJAIS)
    # E o degrau segue funcionando: quem ganha é o que os dados sustentam.
    assert degrau(QUARTO_COM_MEJAIS, "4º item")[0] == 3157  # Zhonya's


def test_no_item_is_bought_twice_in_the_same_page():
    """O mesmo item pode encabeçar dois slots: Zhonya's lidera o 4º e o
    6º. Em blocos separados só parecia estranho; numa lista única de
    compra viraria comprar o mesmo lendário duas vezes."""
    for page in parse_build(COMPLETA).pages:
        for bloco in page.blocks:
            assert len(bloco.items) == len(set(bloco.items)) or bloco.label == "Iniciais"


#: O 6º slot trazendo Malignance, que já é o primeiro item do núcleo.
#: Não é hipótese: é o que o OP.GG devolve para a Annie do meio, porque
#: a estatística de "6º item" conta também quem construiu o núcleo
#: tarde.
SEXTO_REPETE_O_NUCLEO = COMPLETA.replace(
    'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
    'CoreItems([3118],["Malignance"],120,66,0.13)]',
)


def test_the_later_steps_skip_what_the_core_already_bought():
    """Malignance está em "Principais". Repeti-lo no 6º item é mandar
    comprar de novo um lendário que já está no inventário.

    Os degraus seguintes são o que falta comprar, não um segundo
    ranking dos mesmos itens.
    """
    assert 3118 in blocos(SEXTO_REPETE_O_NUCLEO)["Principais"].items
    assert all(
        3118 not in degrau(SEXTO_REPETE_O_NUCLEO, label)
        for label in ("4º item", "5º item", "6º item")
    )


def test_a_step_whose_only_pick_is_already_built_just_drops():
    """Sobrando só item já comprado, o degrau não deixa buraco: some."""
    presentes = list(blocos(SEXTO_REPETE_O_NUCLEO))

    assert "6º item" not in presentes  # só tinha Malignance
    assert degrau(SEXTO_REPETE_O_NUCLEO, "5º item")  # os outros seguem


def test_only_what_the_opgg_measured_comes_out_of_here():
    """O bloco de recompra não é dado do OP.GG, e depende do mapa: fica
    em `itemsets`, que é quem sabe onde a partida acontece."""
    assert "Consumíveis" not in blocos(COMPLETA)


def test_the_starting_items_keep_the_repeated_potion():
    """Duas poções são duas poções, não uma. Iniciais são o núcleo:
    iguais em toda página."""
    assert blocos(COMPLETA)["Iniciais"].items == (1056, 2003, 2003)


def test_the_core_is_the_trio_that_wins():
    assert blocos(COMPLETA)["Principais"].items == (3118, 3152, 4645)
    assert blocos(COMPLETA)["Botas"].items == (3020,)


def test_a_step_carries_the_numbers_of_what_it_recommends():
    """A etiqueta do degrau é uma só, e as alternativas são várias.

    Ela mostra a taxa e a amostra da **primeira** — a compra
    recomendada. Média das três seria um número que não descreve
    nenhuma das compras que o jogador pode fazer.
    """
    quarto = blocos(COMPLETA)["4º item"]

    assert round(quarto.win_rate, 3) == 0.602
    assert quarto.games == 465


def test_the_core_block_carries_its_win_rate():
    """429 vitórias em 816 partidas — o que decide a compra."""
    assert round(blocos(COMPLETA)["Principais"].win_rate, 3) == 0.526


#: `COMPLETA` com o Void Staff perdendo no 5º slot. Aí a leitura por
#: taxa concorda com a por jogo em todos os slots, e as duas páginas
#: saem idênticas — o caso que o desempate por assinatura resolve.
LEITURAS_IGUAIS = COMPLETA.replace(
    'CoreItems([3135],["Void Staff"],68,41,0.16)],',
    'CoreItems([3135],["Void Staff"],68,20,0.16)],',
)


def test_two_readings_that_agree_become_a_single_page():
    """Nem todo campeão tem duas builds. Quando o mais jogado também é o
    de maior taxa em todo slot, a segunda aba seria cópia da primeira."""
    pages = parse_build(LEITURAS_IGUAIS).pages

    assert len(pages) == 1


def test_a_lone_page_carries_no_criterion_in_its_name():
    """Critério só nomeia o que se contrapõe a outro: "Mais jogada"
    sozinho na loja sugere uma segunda aba que não existe."""
    assert parse_build(LEITURAS_IGUAIS).pages[0].label == ""


def test_an_empty_slot_just_drops_out_of_the_list():
    """Campeão sem 6º item não deixa buraco nem bloco vazio: a lista de
    compra encurta e os outros slots seguem."""
    texto = COMPLETA.replace(
        '[CoreItems([4646],["Stormsurge"],2,0,0.25),'
        'CoreItems([3157],["Zhonya\'s Hourglass"],2,1,0.25),'
        'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
        "[]",
    )

    itens = todos_os_itens(texto)

    assert "6º item" not in blocos(texto)
    assert degrau(texto, "4º item") and degrau(texto, "5º item")
    # Stormsurge e Banshee's só existiam no 6º slot.
    assert 4646 not in itens and 3102 not in itens
    assert 3135 in itens  # Void Staff, que veio do 4º e do 5º


def _com_ultimos(itens: str) -> str:
    """`COMPLETA` acrescida de um `last_items`, que ela não traz."""
    return COMPLETA.replace(
        "class Data: core_items,boots,starter_items,fourth_items,"
        "fifth_items,sixth_items,summoner_spells,runes\n",
        "class Data: core_items,boots,starter_items,fourth_items,"
        "fifth_items,sixth_items,last_items,summoner_spells,runes\n",
    ).replace(
        "CoreItems([4,14],[4,14],6384,3240,0.7),",
        itens + "CoreItems([4,14],[4,14],6384,3240,0.7),",
    )


#: O `last_items` de uma captura real (Ahri, meio) — o campo que o app
#: leu por último. Rabadon's já encabeça outro degrau; Horizon Focus
#: não aparece em lugar nenhum da lista de compra, e é o que sobra.
COM_ULTIMO_ITEM = _com_ultimos(
    '[CoreItems([4628],["Horizon Focus"],669,435,0.19),'
    'CoreItems([3089],["Rabadon\'s Deathcap"],606,327,0.17)],'
)


def test_the_most_built_items_become_the_situational_block():
    """`last_items` não é "o último item", por mais que o nome diga.

    É o ranking dos itens mais construídos do campeão inteiro — no
    Darius de Diamante+ ele mede 22438 partidas contra 1374 do núcleo,
    e um "último item" não pode ter dezesseis vezes mais amostra que o
    começo da build. Lido como degrau, mandava fechar a build com item
    de 350 de ouro. Lido como o que é, vira a lista de saídas que a
    ordem de compra ainda não cobriu.
    """
    assert "Último item" not in blocos(COM_ULTIMO_ITEM)
    assert degrau(COM_ULTIMO_ITEM, "Situacionais") == (4628,)


def test_the_situational_block_skips_what_is_already_on_screen():
    """Alternativa repetida não oferece situação nenhuma.

    Rabadon's lidera o 5º item; repeti-la aqui só ocuparia a linha que
    o item novo ocuparia. O filtro é contra **tudo o que está na
    tela**, não só contra as compras recomendadas — as alternativas dos
    degraus anteriores também já estão à vista.
    """
    assert 3089 in todos_os_itens(COMPLETA)  # Rabadon's, no 4º e no 5º
    assert 3089 not in degrau(COM_ULTIMO_ITEM, "Situacionais")


def test_a_situational_block_with_nothing_new_just_drops():
    """Sobrando só o que a build já comprou, o bloco não aparece."""
    texto = _com_ultimos(
        '[CoreItems([3089],["Rabadon\'s Deathcap"],669,435,0.19),'
        'CoreItems([3135],["Void Staff"],606,327,0.17)],'
    )

    assert "Situacionais" not in blocos(texto)


def test_a_starting_item_is_never_advice_for_the_late_game():
    """O ranking dos mais construídos é liderado pelo que se compra aos
    quatro minutos: na Ahri de Mestre+ o bloco saía `(Bastão Rúnico,
    Lacre Sombrio)` — 350 de ouro oferecidos como saída de fim de
    partida, quando o jogador já vendeu o dele há vinte minutos."""
    texto = _com_ultimos(
        '[CoreItems([1082],["Dark Seal"],669,435,0.19),'
        'CoreItems([4628],["Horizon Focus"],606,327,0.17)],'
    )

    assert degrau(texto, "Situacionais") == (4628,)


#: `COMPLETA` com o 6º item trazendo uma alternativa só. Acontece de
#: verdade — o Thresh suporte volta assim — e era o caso que punha o
#: bloco fora de lugar na loja.
UM_SEXTO_ITEM = COMPLETA.replace(
    '[CoreItems([4646],["Stormsurge"],2,0,0.25),'
    'CoreItems([3157],["Zhonya\'s Hourglass"],2,1,0.25),'
    'CoreItems([3102],["Banshee\'s Veil"],1,1,0.13)]',
    '[CoreItems([4646],["Stormsurge"],19,10,0.25)]',
)


def test_a_step_with_a_single_alternative_keeps_its_place_in_the_order():
    """O que decide a posição na lista de compra é o campo, não quantas
    alternativas voltaram. Contando alternativas, um 6º item sozinho
    virava “núcleo” e era comprado antes do 4º."""
    assert list(blocos(UM_SEXTO_ITEM)) == DEGRAUS_COM_SEXTO
    # Stormsurge é o 6º slot: entra por último, mesmo sozinho.
    assert degrau(UM_SEXTO_ITEM, "6º item") == (4646,)


def test_the_core_blocks_never_get_an_item_name_appended():
    """Iniciais, botas e principais são o build inteiro, não uma escolha
    entre alternativas: nomear cada um só faria a etiqueta crescer."""
    labels = [b.label for b in parse_build(COMPLETA).pages[0].blocks[:3]]

    assert labels == ["Iniciais", "Botas", "Principais"]


def test_an_answer_without_items_still_gives_the_runes():
    """Runa e item são independentes: um faltar não leva o outro.
    """
    build = parse_build(RESPOSTA)

    assert build.pages == ()
    assert build.perks[0] == 8112


# --- o material de leitura -----------------------------------------------

#: Captura do servidor real (Yasuo, meio, Diamante+) pedindo também o
#: que não se aplica no cliente: ordem de habilidade, confrontos,
#: duplas e o boletim do campeão. Vale reparar em três coisas que o
#: parser tem de aguentar. As duas listas de confronto chegam com a
#: mesma etiqueta `StrongCounter`, e só a posição em `Data` diz qual é
#: a favor e qual é contra. As duplas chegam agrupadas por rota, com a
#: classe chamada `Jungle` mesmo quando o grupo é de suporte. E o
#: pedido leva as cinco rotas, mas `mid` volta recusado em
#: `_field_diagnostics` — um meio não faz dupla consigo mesmo.
LEITURA = (
    "class LolGetChampionAnalysis: data,_field_diagnostics\n"
    "class Data: summary,damage_type,strong_counters,weak_counters,"
    "synergies,summoner_spells,runes,skills,skill_masteries\n"
    "class Summary: average_stats\n"
    "class AverageStats: play,win_rate,pick_rate,ban_rate,kda,tier,rank,tier_data\n"
    "class TierData: tier,rank,rank_prev,rank_prev_patch\n"
    "class StrongCounter: champion_id,champion_name,play,win,my_win_rate,"
    "counter_win_rate,win_rate\n"
    "class Synergies: jungle,adc,support\n"
    "class Jungle: champion_id,champion_name,position,synergy_champion_id,"
    "synergy_champion_name,synergy_position,score_rank,score,play,win,"
    "win_rate,synergy_tier_data\n"
    "class CoreItems: ids,ids_names,play,win,pick_rate\n"
    "class Runes: id,primary_page_id,primary_page_name,primary_rune_ids,"
    "primary_rune_names,secondary_page_id,secondary_page_name,"
    "secondary_rune_ids,secondary_rune_names,stat_mod_ids,stat_mod_names,"
    "play,win,pick_rate\n"
    "class Skills: order,play,win,pick_rate\n"
    "class SkillMasteries: ids,play,win,pick_rate,builds\n"
    "class FieldDiagnostics: unmatched_fields,hint\n"
    "\n"
    "LolGetChampionAnalysis(Data("
    "Summary(AverageStats(90305,0.49,0.12,0.17,1.62,3,44,TierData(3,44,44,52))),"
    '"AD",'
    '[StrongCounter(39,"Irelia",459,258,0.56,0.44,0.56),'
    'StrongCounter(142,"Zoe",639,350,0.55,0.45,0.55)],'
    '[StrongCounter(136,"Aurelion Sol",313,128,0.41,0.59,0.59),'
    'StrongCounter(92,"Riven",204,83,0.41,0.59,0.59)],'
    "Synergies("
    '[Jungle(157,"Yasuo","MID",76,"Nidalee","JUNGLE",7,0,751,408,0.54,'
    "TierData(1,2,2,4))],"
    '[Jungle(157,"Yasuo","MID",112,"Viktor","ADC",9,0,676,355,0.53,'
    "TierData(2,7,6,2))],"
    '[Jungle(157,"Yasuo","MID",89,"Leona","SUPPORT",8,0,677,356,0.53,'
    "TierData(1,2,2,3))]),"
    "CoreItems([4,14],[4,14],26098,12480,0.53),"
    'Runes(8008,8000,"Precision",[8008,9101,9104,8299],'
    '["Lethal Tempo","Absorb Life","Legend: Alacrity","Last Stand"],'
    '8400,"Resolve",[8444,8451],["Second Wind","Overgrowth"],'
    "[5005,5008,5001],[5005,5008,5001],12907,5819,0.26),"
    'Skills(["Q","E","W","Q","Q","R","Q","E","Q","E","R","E","E","W","W"],'
    "14965,8355,0.49),"
    'SkillMasteries(["Q","E","W"],29746,16590,0.98,[])),'
    'FieldDiagnostics(["data.synergies.mid[]"],"were skipped"))'
)


def test_it_reads_the_skill_order():
    build = parse_build(LEITURA)

    assert build.skill_order[:6] == ("Q", "E", "W", "Q", "Q", "R")
    assert len(build.skill_order) == 15


def test_it_reads_which_skill_to_max_first():
    build = parse_build(LEITURA)

    assert build.skill_max == ("Q", "E", "W")


def test_both_counter_lists_keep_our_own_win_rate():
    """As duas listas vêm com a mesma etiqueta e três taxas cada.

    O terceiro campo, `win_rate`, troca de dono: vale a nossa quando
    vencemos e a do adversário quando perdemos. Guardar sempre
    `my_win_rate` é o que permite ler as duas listas na mesma escala —
    0.56 contra Irelia e 0.41 contra Riven falam do Yasuo nas duas.
    """
    build = parse_build(LEITURA)

    assert [(c.champion, c.win_rate) for c in build.strong_against] == [
        ("Irelia", 0.56),
        ("Zoe", 0.55),
    ]
    assert [(c.champion, c.win_rate) for c in build.weak_against] == [
        ("Aurelion Sol", 0.41),
        ("Riven", 0.41),
    ]


def test_the_counters_carry_the_id_that_fetches_the_icon():
    build = parse_build(LEITURA)

    assert build.strong_against[0].champion_id == 39


def test_the_synergies_come_flat_but_still_say_which_lane():
    """Agrupadas por rota na resposta, achatadas aqui.

    Quem diz a rota é cada entrada, não o nome do grupo — a classe se
    chama `Jungle` até no grupo do suporte. Ler de dentro é o que faz
    isso continuar valendo quando o campeão muda de posição e o
    servidor troca os grupos.
    """
    build = parse_build(LEITURA)

    assert [(s.champion, s.position) for s in build.synergies] == [
        ("Nidalee", "JUNGLE"),
        ("Viktor", "ADC"),
        ("Leona", "SUPPORT"),
    ]


def test_the_synergy_is_the_partner_not_ourselves():
    """Cada entrada traz os dois lados; o que interessa é o outro."""
    build = parse_build(LEITURA)

    assert build.synergies[0].champion_id == 76  # Nidalee, não 157


def test_it_reads_the_report_card():
    build = parse_build(LEITURA)

    assert build.stats.win_rate == 0.49
    assert build.stats.games == 90305
    assert build.stats.tier == 3
    assert build.stats.rank == 44


def test_it_reads_the_damage_type():
    build = parse_build(LEITURA)

    assert build.damage_type == "AD"


def test_the_reading_material_is_optional():
    """A resposta antiga não tem nada disso, e continua virando build.

    É a diferença que importa entre esses campos e as runas: sem grade
    de counters a tela fica mais pobre, sem página de runas a partida
    começa errada. Só o segundo caso justifica recusar tudo.
    """
    build = parse_build(RESPOSTA)

    assert build.skill_order == ()
    assert build.strong_against == ()
    assert build.synergies == ()
    assert build.stats is None
    assert build.perks[0] == 8112


def test_a_skill_order_with_junk_is_dropped_whole():
    """Letra que não nomeia habilidade viraria casa vazia na tela."""
    quebrado = LEITURA.replace('"Q","E","W","Q"', '"Q","E","W","X"')

    assert parse_build(quebrado).skill_order == ()


def test_a_broken_report_card_does_not_sink_the_build():
    quebrado = LEITURA.replace("AverageStats(90305,0.49", "AverageStats(oi,tchau")

    build = parse_build(quebrado)

    assert build.stats is None
    assert build.perks[0] == 8008


# --- a fonte -------------------------------------------------------------


#: `RESPOSTA` com um núcleo de amostra folgada enxertado.
#:
#: A captura crua não traz campo de item nenhum, e desde que o arsenal
#: passou a escorregar de elo quando falta amostra isso significa "elo
#: seco": qualquer `fetch` sobre ela dispararia duas perguntas extras,
#: e os testes que contam idas à rede contariam o alargamento junto.
#: Aqui o núcleo tem 816 partidas — o elo pedido basta, e a pergunta é
#: uma só, que é o que esses testes querem medir.
RESPOSTA_FIRME = RESPOSTA.replace(
    "class Data: summoner_spells,runes\n",
    "class Data: core_items,summoner_spells,runes\n"
    "class CoreItems: ids,ids_names,play,win,pick_rate\n",
).replace(
    "LolGetChampionAnalysis(Data(SummonerSpells(",
    "LolGetChampionAnalysis(Data(CoreItems([3118,3152,4645],"
    '["Malignance","Hextech Rocketbelt","Shadowflame"],816,429,0.16),'
    "SummonerSpells(",
)


def com_amostra(partidas: int) -> str:
    """`RESPOSTA_FIRME` com o núcleo medido em tantas partidas."""
    return RESPOSTA_FIRME.replace(
        "816,429,0.16", f"{partidas},{partidas // 2},0.16"
    )


class TierSend:
    """Uma resposta por elo, para acompanhar o escorregão do arsenal.

    Elo ausente do mapa responde vazio — que é como o servidor de
    verdade avisa que não tem partidas o bastante para este campeão
    nesta rota. Vazio não é falha de rede: uma pede perguntar mais
    largo, a outra pede desistir.
    """

    def __init__(self, answers):
        self.answers = dict(answers)
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        return self.answers.get(arguments["tier"], "")

    @property
    def tiers(self):
        return [c["tier"] for c in self.calls]


class FakeSend:
    """Substitui a ida à rede, guardando o que foi pedido."""

    def __init__(self, answer=RESPOSTA_FIRME, fail=False):
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


def test_a_different_elo_can_be_asked_too():
    """O elo é um parâmetro, não um valor fixo — quem chama escolhe."""
    send = FakeSend()

    OpggSource(send=send).fetch("Annie", "middle", aram=False, tier="challenger")

    assert send.calls[0]["tier"] == "challenger"


def test_the_same_champion_in_a_different_elo_is_asked_again():
    """Trocar o elo nos ajustes não pode devolver a build do elo antigo."""
    send = FakeSend()
    source = OpggSource(send=send)

    source.fetch("Annie", "middle", aram=False, tier="diamond_plus")
    source.fetch("Annie", "middle", aram=False, tier="challenger")

    assert len(send.calls) == 2


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
    build = OpggSource(send=FakeSend(RESPOSTA)).fetch("Annie", "middle", aram=False)

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


# --- o elo do arsenal ----------------------------------------------------


def test_a_thin_elo_gets_its_arsenal_from_a_wider_one():
    """Elo alto mede poucas partidas, e degrau de item é medido por
    conta: no Desafiante o 5º e o 6º item da Ashe saíam de amostras de
    duas partidas — com 0% de vitória entrando na loja com a mesma cara
    de recomendação que o item de mil partidas.

    Os números são os do servidor: 17 partidas no Desafiante contra
    1125 em Mestre+, no mesmo campeão e na mesma rota.
    """
    send = TierSend(
        {"challenger": com_amostra(17), "master_plus": com_amostra(1125)}
    )

    build = OpggSource(send=send).fetch(
        "Ashe", "bottom", aram=False, tier="challenger"
    )

    assert send.tiers == ["challenger", "master_plus"]
    assert build.sample == 1125
    assert build.item_tier == "master_plus"


def test_only_the_arsenal_slips_elo():
    """Quem escolhe "Desafiante" nos Ajustes está pedindo a página de
    runa de quem joga melhor, e página de runa é escolha estável — o
    campeão usa a mesma com 80 partidas ou com 8000.

    Escorregar só o arsenal também preserva o comparador de elos da
    tela de runas, que ficaria mostrando a mesma página três vezes se o
    elo trocasse por baixo dele.
    """
    largo = com_amostra(1125).replace(
        "SummonerSpells([4,14],[4,14]", "SummonerSpells([4,12],[4,12]"
    )
    send = TierSend({"challenger": com_amostra(17), "master_plus": largo})

    build = OpggSource(send=send).fetch(
        "Ashe", "bottom", aram=False, tier="challenger"
    )

    assert build.spells == (4, 14)  # os do elo pedido
    assert build.sample == 1125  # o arsenal veio do largo


def test_an_elo_that_holds_its_sample_is_never_asked_twice():
    """O alargamento custa segundos de rede por pergunta. Amostra que
    já basta não paga esse preço — e é o caso comum."""
    send = TierSend({"challenger": com_amostra(816)})

    build = OpggSource(send=send).fetch(
        "LeeSin", "jungle", aram=False, tier="challenger"
    )

    assert send.tiers == ["challenger"]
    assert build.item_tier == ""


def test_a_silent_elo_gives_way_to_the_wider_one_whole():
    """O campeão fora do lugar habitual é quem mais precisa de conselho,
    e é justamente quem o elo alto não mede: a Sona no topo não existe
    no Desafiante — nem a página de runa, nem o arsenal.

    Aí o elo amplo entra inteiro, porque a alternativa é o jogador não
    receber nada. Antes disso o `fetch` devolvia ``None``.
    """
    send = TierSend({"master_plus": com_amostra(1125)})

    build = OpggSource(send=send).fetch(
        "Sona", "top", aram=False, tier="challenger"
    )

    assert build is not None
    assert build.perks[0] == 8112
    assert build.item_tier == "master_plus"


def test_the_widening_gives_up_after_two_tries():
    """Cada pergunta custa uns quatro segundos, e a seleção de campeão
    não espera. Dois degraus cobrem o que o servidor tinha a oferecer:
    medido no Teemo suporte, que sai de nada para 71 partidas em
    Diamante+. Quem precisa de mais que isso — a Sona do topo — não
    chega a uma amostra que valha a espera nem em `all`.
    """
    send = TierSend({})

    build = OpggSource(send=send).fetch(
        "Sona", "top", aram=False, tier="challenger"
    )

    assert build is None
    assert send.tiers == ["challenger", "master_plus", "diamond_plus"]


def test_a_network_failure_never_triggers_the_widening():
    """Rede caída e elo seco chegavam os dois como ausência, e mereciam
    tratamentos opostos. Confundi-los custava três idas à rede morta
    pelo mesmo nada — e três vezes a espera antes de cair na Riot.
    """
    send = FakeSend(fail=True)

    assert OpggSource(send=send).fetch("Annie", "middle", aram=False) is None
    assert len(send.calls) == 1
