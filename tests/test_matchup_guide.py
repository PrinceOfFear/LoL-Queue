"""A leitura rica do guia de confronto, sobre uma resposta gravada.

A fixture é a captura literal de `lol_get_lane_matchup_guide` para
Ahri contra Zed no meio — 42 KB, nada recortado. Gravada de propósito:
teste que depende de rede falha por motivo que não é o do teste, e
esta resposta é justamente a que precisa continuar sendo entendida
quando o servidor mudar de forma.
"""

import json
from pathlib import Path

from lolqueue.core import matchup

AHRI_ZED = json.loads(
    (Path(__file__).parent / "fixtures" / "matchup_ahri_zed.json").read_text(
        encoding="utf-8"
    )
)["data"]


def build():
    return matchup.parse_guide(AHRI_ZED)


def blocos():
    return {block.label: block for block in build().pages[0].blocks}


def test_the_guide_carries_a_whole_rune_page():
    """Nove runas, as duas árvores, na ordem que o cliente instala."""
    lida = build()

    assert lida.style == 8100 and lida.sub_style == 8200
    assert lida.perks == (8112, 8139, 8140, 8106, 8210, 8226, 5005, 5008, 5001)
    assert lida.spells == (4, 14)


def test_a_second_rune_page_needs_more_than_twenty_three_games():
    """O servidor manda cinco páginas; quatro delas têm 39, 28, 23 e 22
    partidas. 60,9% em 23 jogos não é uma segunda build, é ruído — e
    página de runa alternativa é a recomendação mais cara de errar,
    porque o app a instala no cliente."""
    paginas = build().rune_pages

    assert len(paginas) == 1
    assert paginas[0].games == 286
    # Página única não carrega critério no nome: não há aba rival.
    assert paginas[0].label == ""


def test_two_readings_that_disagree_become_two_named_pages():
    """Quando a alternativa tem amostra de verdade, ela vira uma aba com
    o critério no nome — é o que o `loadout` oferece para trocar."""
    dobrado = dict(AHRI_ZED)
    dobrado["runes"] = [
        AHRI_ZED["runes"][0],
        # A mesma segunda página, com amostra e fatia que se sustentam.
        {**AHRI_ZED["runes"][1], "play": 220, "win": 130, "pick_rate": 0.36},
    ]

    paginas = matchup.parse_guide(dobrado).rune_pages

    assert [page.label for page in paginas] == ["Mais jogada", "Maior taxa"]
    assert paginas[0].games == 286
    assert paginas[1].games == 220
    # A build principal segue a mais jogada; a outra é oferta, não troca
    # silenciosa.
    assert matchup.parse_guide(dobrado).perks == paginas[0].perks


def test_the_shopping_list_comes_in_purchase_order():
    """`single_items` vem aberto por profundidade de compra, e é isso
    que a loja mostra: um degrau por vez, não quatro títulos de um item
    cada como o `champion_analysis` obrigava."""
    assert list(blocos()) == [
        "Iniciais",
        "Botas",
        "1º item",
        "2º item",
        "3º item",
        "4º item",
        "Último item",
    ]


def test_each_step_shows_the_alternatives_and_not_a_single_answer():
    """O estrago que motivou tudo: a loja recebia um item por bloco, sem
    contexto, como se não houvesse escolha."""
    primeiro = blocos()["1º item"]

    assert len(primeiro.items) == 3
    assert primeiro.items[0] == 2503  # Blackfire Torch, o que os dados sustentam
    assert 3118 in primeiro.items  # Malignance, o mais comprado, segue à vista


def test_the_step_carries_the_numbers_that_justify_it():
    """Taxa e fatia de escolha andam juntas: 55% num item escolhido em
    25% das partidas diz outra coisa que 55% num escolhido em 2%."""
    primeiro = blocos()["1º item"]

    assert round(primeiro.win_rate, 3) == 0.55
    assert primeiro.pick_rate == 0.2482
    assert primeiro.games == 140


def test_an_item_with_six_games_never_reaches_the_shop():
    """Zhonya's aparece no 1º item com 6 partidas e 66% de vitória. É o
    mesmo ruído que colocava "Banshee's Veil — 100%" no topo do arsenal
    antigo."""
    assert 3157 not in blocos()["1º item"].items


def test_the_recommended_buy_never_repeats_along_the_list():
    """Zhonya's encabeça o 2º, o 3º e o 4º degrau, porque o OP.GG mede
    cada profundidade por conta. Como compra recomendada isso viraria
    "compre Zhonya's três vezes"; como alternativa ele pode reaparecer,
    que é só dizer que o item segue bom mais adiante."""
    lideres = [
        block.items[0]
        for label, block in blocos().items()
        if label not in ("Iniciais", "Botas")
    ]

    assert len(lideres) == len(set(lideres))


def test_a_step_that_has_nothing_left_to_buy_just_disappears():
    """O 5º degrau da Ahri só repete o que os anteriores já mandaram
    comprar. Bloco vazio na loja é pior que um degrau a menos."""
    assert "5º item" not in blocos()


def test_the_boots_answer_the_opponent():
    """É o que o guia de confronto tem e a análise de campeão não:
    contra Zed, as botas de armadura aparecem em 12% das partidas com
    taxa melhor que as de feitiçaria, e passam na frente."""
    botas = blocos()["Botas"]

    assert botas.items[0] == 3047  # Plated Steelcaps
    assert 3020 in botas.items  # Sorcerer's Shoes segue como alternativa


def test_the_reading_material_comes_along():
    """Ordem de habilidade e boletim do campeão vêm da mesma resposta —
    não custam viagem nenhuma e o app já sabe desenhar os dois."""
    lida = build()

    assert lida.skill_order[:3] == ("W", "Q", "E")
    assert lida.skill_max == ("Q", "W", "E")
    assert lida.stats.games == 14706


def test_half_a_rune_page_is_no_page_at_all():
    """Entrar em partida com três runas certas e o resto em branco é um
    estrago silencioso. Faltando runa, a build inteira é ``None`` e o
    app volta para a fonte que responde sem saber o adversário."""
    quebrado = dict(AHRI_ZED)
    quebrado["runes"] = [
        {**AHRI_ZED["runes"][0], "stat_mod_ids": [5005, 5008]}  # oito runas
    ]

    assert matchup.parse_guide(quebrado) is None


def test_without_summoner_spells_there_is_no_build():
    """Mesma régua dos feitiços: o cliente instala o par, e meio par não
    existe."""
    quebrado = dict(AHRI_ZED)
    quebrado["summoner_spells"] = []

    assert matchup.parse_guide(quebrado) is None


def test_the_tip_and_the_build_come_from_the_same_answer():
    """Uma viagem só. A dica escrita e a build saem do mesmo JSON de 42
    KB que já era baixado inteiro e lido só pela dica."""
    lida = matchup.parse_matchup({"data": AHRI_ZED}, "Ahri", "Zed")

    assert lida.tip
    assert lida.build is not None
    assert lida.build.perks == build().perks


def test_an_answer_with_a_build_but_no_tip_is_still_an_answer():
    """A régua antiga era só a dica escrita. Uma resposta com cinco
    páginas de runa e a lista de compra aberta não é vazia."""
    sem_dica = dict(AHRI_ZED)
    sem_dica["opponent_champion_tip"] = ""

    lida = matchup.parse_matchup({"data": sem_dica}, "Ahri", "Zed")

    assert lida is not None and lida.tip == ""
    assert lida.build is not None


# ---------- a queda para o boletim do campeão ----------
#
# `lol_get_lane_matchup_guide` exige `opponent_champion`. Sem esta
# queda, toda seleção antes de o adversário travar mostraria tela
# vazia — e é onde o usuário passa a maior parte do tempo.

BRUTO = (Path(__file__).parent / "fixtures" / "matchup_ahri_zed.json").read_text(
    encoding="utf-8"
)


class FonteFalsa:
    """Um `opgg.Source` de mentira: registra o que perguntaram."""

    def __init__(self, build="build-do-campeao"):
        self.build = build
        self.chamadas = []

    def fetch(self, champion, position, aram, tier=None):
        self.chamadas.append((champion, position, aram, tier))
        return self.build


def fonte(texto=BRUTO):
    return matchup.MatchupSource(send=lambda arguments: texto)


def test_the_guide_wins_when_the_opponent_is_known():
    reserva = FonteFalsa()
    build, contra = fonte().fetch_build("Ahri", "Zed", "middle", fallback=reserva)

    assert contra == "Zed"
    assert build is not None and build.perks[0] == 8112
    # A reserva nem foi consultada: uma viagem, não duas.
    assert reserva.chamadas == []


def test_an_unknown_opponent_falls_back_instead_of_going_blank():
    reserva = FonteFalsa()
    build, contra = fonte().fetch_build("Ahri", "", "middle", fallback=reserva)

    assert build == "build-do-campeao"
    # Vazio de propósito: a tela não pode escrever "contra Zed" quando
    # a build não veio de confronto nenhum.
    assert contra == ""
    assert reserva.chamadas == [("Ahri", "middle", False, None)]


def test_a_guide_without_an_approved_rune_page_also_falls_back():
    reserva = FonteFalsa()
    vazio = fonte('{"data": {"opponent_champion_tip": "cuidado com o R"}}')
    build, contra = vazio.fetch_build("Ahri", "Zed", "middle", fallback=reserva)

    assert build == "build-do-campeao"
    assert contra == ""


def test_without_a_fallback_the_caller_gets_an_honest_nothing():
    assert fonte("{}").fetch_build("Ahri", "Zed", "middle") == (None, "")


def test_a_broken_fallback_never_takes_the_screen_down():
    class Quebrada:
        def fetch(self, *args, **kwargs):
            raise RuntimeError("sem rede")

    build, contra = fonte("{}").fetch_build(
        "Ahri", "Zed", "middle", fallback=Quebrada()
    )
    assert (build, contra) == (None, "")


def test_the_chosen_tier_reaches_the_fallback():
    reserva = FonteFalsa()
    fonte("{}").fetch_build("Ahri", "", "middle", fallback=reserva, tier="diamond_plus")
    assert reserva.chamadas == [("Ahri", "middle", False, "diamond_plus")]
