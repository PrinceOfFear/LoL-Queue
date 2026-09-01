"""Testes das zonas do mapa.

A geometria aqui foi conferida contra a textura oficial do minimapa
(`tests/fixtures/sr_minimap_canonico.png`, baixada do CommunityDragon),
desenhando as zonas por cima e olhando onde cada uma caía. Estes testes
travam o resultado dessa conferência, incluindo a posição dos doze
acampamentos da selva.

Os pontos de amostra da selva genérica são escolhidos longe dos
acampamentos de propósito: perto deles quem responde é a regra mais
específica, e responde certo.

O detalhe que mais confunde quem lê: as quatro selvas do Rift ficam nos
pontos cardeais, não nos cantos. Os cantos são as bases e as curvas das
rotas laterais; quem ocupa norte/sul/leste/oeste é a selva.
"""

from __future__ import annotations

from math import cos, hypot, pi, sin, sqrt

import pytest

from lolqueue.vision.zones import (
    BARON_PIT,
    BLUE_BASE,
    CAMP_RADIUS,
    CAMPS,
    DRAGON_PIT,
    OBJECTIVE_RADIUS,
    RED_BASE,
    STABLE_MARGIN,
    classify,
    describe,
)

AZUL = 1
VERMELHO = -1


def test_pits_have_their_own_name():
    """Os covis ganham de rio e de selva: eles têm nome próprio."""
    assert classify(*BARON_PIT).key == "baron"
    assert classify(*DRAGON_PIT).key == "dragon"


def test_pits_are_not_swapped():
    """Barão fica na metade de cima do mapa e Dragão na de baixo."""
    bx, by = BARON_PIT
    dx, dy = DRAGON_PIT
    assert bx + by < 1.0
    assert dx + dy > 1.0


@pytest.mark.parametrize("ponto", [(0.30, 0.70), (0.50, 0.50), (0.70, 0.30)])
def test_mid_runs_along_the_diagonal(ponto):
    """A rota do meio é a diagonal que liga as duas bases."""
    assert classify(*ponto).key == "mid"


def test_river_runs_on_the_other_diagonal():
    """O rio corre na diagonal oposta à do meio."""
    assert classify(0.24, 0.24).key == "river_top"
    assert classify(0.78, 0.78).key == "river_bot"


@pytest.mark.parametrize(
    "nome, ponto, chave, lado",
    [
        ("oeste", (0.19, 0.63), "jungle_top", AZUL),
        ("norte", (0.55, 0.20), "jungle_top", VERMELHO),
        ("sul", (0.45, 0.80), "jungle_bot", AZUL),
        ("leste", (0.81, 0.37), "jungle_bot", VERMELHO),
    ],
)
def test_the_four_jungle_quadrants(nome, ponto, chave, lado):
    """As quatro selvas ficam nos pontos cardeais, não nos cantos."""
    zona = classify(*ponto)
    assert zona.key == chave, nome
    assert zona.side == lado, nome


def test_bases_win_over_mid():
    """As bases ficam nas pontas da mid e não podem ser engolidas por ela."""
    assert classify(*BLUE_BASE).key == "blue_base"
    assert classify(*RED_BASE).key == "red_base"


def test_adjacent_camp_areas_do_not_overlap():
    """O meio entre dois campos não pode escolher o primeiro da lista.

    Esta era uma fonte literal de falso aviso: Blue e lobos ficam a
    aproximadamente 0,10 do mapa um do outro, mas dois raios de 0,055
    se cruzavam. Quem caía no cruzamento recebia "blue" por ordem de
    iteração, não por estar no blue.
    """
    for side in (AZUL, VERMELHO):
        camps = [camp for camp in CAMPS if camp[3] == side]
        for index, left in enumerate(camps):
            for right in camps[index + 1 :]:
                distance = hypot(left[1] - right[1], left[2] - right[2])
                assert distance > CAMP_RADIUS * 2


def test_objective_area_does_not_swallow_the_nearest_camp():
    """Perto do covil ainda pode ser red; são duas localizações distintas."""
    for pit in (BARON_PIT, DRAGON_PIT):
        nearest = min(
            hypot(camp[1] - pit[0], camp[2] - pit[1]) for camp in CAMPS
        )
        assert nearest > OBJECTIVE_RADIUS + CAMP_RADIUS


def test_the_space_between_blue_and_wolves_stays_generic_jungle():
    """Sem localização precisa, a resposta honesta é selva, não um campo."""
    blue = next(camp for camp in CAMPS if camp[0] == "blue" and camp[3] == AZUL)
    wolves = next(
        camp for camp in CAMPS if camp[0] == "wolves" and camp[3] == AZUL
    )
    midpoint = ((blue[1] + wolves[1]) / 2, (blue[2] + wolves[2]) / 2)

    assert classify(*midpoint).key not in {"blue", "wolves"}


@pytest.mark.parametrize(
    "ponto", [(0.11, 0.25), (0.25, 0.11), (0.11, 0.11)]
)
def test_top_lane_hugs_the_upper_left_edges(ponto):
    """A rota de cima corre colada na borda esquerda e na de cima."""
    assert classify(*ponto).key == "top_lane"


@pytest.mark.parametrize(
    "ponto", [(0.89, 0.75), (0.75, 0.89), (0.89, 0.89)]
)
def test_bot_lane_hugs_the_lower_right_edges(ponto):
    """A rota de baixo corre colada na borda direita e na de baixo."""
    assert classify(*ponto).key == "bot_lane"


def test_every_point_gets_a_name():
    """Nunca ficar sem resposta: silêncio é o pior resultado num gank."""
    for i in range(41):
        for j in range(41):
            zona = classify(i / 40, j / 40)
            assert zona.label, (i, j)


def test_description_takes_the_listener_side():
    """A mesma selva é 'sua' para um time e 'dele' para o outro."""
    oeste = classify(0.19, 0.63)
    assert describe(oeste, ally_side=AZUL) == "na sua selva de cima"
    assert describe(oeste, ally_side=VERMELHO) == "na selva de cima dele"


def test_description_without_a_known_side_stays_neutral():
    """Sem saber o time do jogador, não inventar dono."""
    oeste = classify(0.19, 0.63)
    assert describe(oeste, ally_side=0) == "na selva de cima"


def test_neutral_zones_never_gain_an_owner():
    """Rio e covis são de ninguém, mesmo sabendo o time de quem ouve."""
    for ponto in [BARON_PIT, DRAGON_PIT, (0.24, 0.24), (0.50, 0.50)]:
        zona = classify(*ponto)
        assert describe(zona, AZUL) == zona.label
        assert describe(zona, VERMELHO) == zona.label


def test_the_place_carries_the_side_and_not_only_the_name():
    """Duas selvas de cima existem, e a frase distingue uma da outra.

    Comparar dois quadros pela chave sozinha faz o app achar que o
    jungler não saiu do lugar quando ele atravessou o mapa inteiro: as
    duas metades da mesma rota partilham a chave e recebem frases
    opostas — "na sua selva de cima" e "na selva de cima dele".
    """
    from lolqueue.vision.zones import place

    sua, dele = place(0.19, 0.63), place(0.63, 0.19)
    assert sua[0] == dele[0] == "jungle_top"
    assert sua != dele


def test_a_point_on_a_border_is_not_well_inside():
    """Em cima da divisa, o nome do lugar não vale como leitura firme."""
    from lolqueue.vision.zones import well_inside

    assert not well_inside(0.44, 0.30)


def test_a_point_in_the_middle_of_a_zone_is_well_inside():
    """Longe de qualquer divisa, o nome é o nome; nada a confirmar."""
    from lolqueue.vision.zones import well_inside

    assert well_inside(*BARON_PIT)
    assert well_inside(0.19, 0.63)


def test_a_diagonal_camp_edge_is_not_firm():
    """As sondas diagonais protegem a borda redonda de um acampamento."""
    from lolqueue.vision.zones import well_inside

    blue = next(camp for camp in CAMPS if camp[0] == "blue" and camp[3] == AZUL)
    radius = CAMP_RADIUS - STABLE_MARGIN * 0.8
    point = (
        blue[1] + radius / sqrt(2),
        blue[2] + radius / sqrt(2),
    )

    assert classify(*point).key == "blue"
    assert not well_inside(*point)


def test_sixteen_probes_cover_the_slanted_gap_left_by_eight():
    """Uma curva entre duas sondas também é divisa no modo máximo.

    Com oito direções, o ponto a 22,5° fica entre duas sondas. Ele está
    só 0,02425 para dentro do blue, portanto não pode passar pela margem
    estrita de 0,025 mesmo que os oito raios usuais ainda não o alcancem.
    """
    from lolqueue.vision.zones import well_inside

    blue = next(camp for camp in CAMPS if camp[0] == "blue" and camp[3] == AZUL)
    strict_margin = 0.025
    radius = CAMP_RADIUS - strict_margin + 0.00075
    point = (
        blue[1] + radius * cos(pi / 8),
        blue[2] + radius * sin(pi / 8),
    )

    assert classify(*point).key == "blue"
    assert well_inside(*point, strict_margin, probes=8)
    assert not well_inside(*point, strict_margin, probes=16)


def test_being_well_inside_does_not_depend_on_staying_on_the_map():
    """As sondas saem do quadrado nas beiradas, e isso não pode explodir.

    `classify` responde para qualquer ponto; grampear a sonda na borda
    faria as quatro caírem no mesmo lugar e todo canto do mapa passaria
    por firme justamente onde a leitura é pior.
    """
    from lolqueue.vision.zones import well_inside

    for ponto in [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (0.5, 0.0)]:
        assert well_inside(*ponto) in (True, False)
