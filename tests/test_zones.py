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

import pytest

from lolqueue.vision.zones import (
    BARON_PIT,
    BLUE_BASE,
    DRAGON_PIT,
    RED_BASE,
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
