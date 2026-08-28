"""A medição do minimapa dentro da imagem do jogo.

Todos os casos montam uma cena falsa em volta de um minimapa
verdadeiro — `tests/fixtures/minimap_sample.png`, recortado de uma
partida real. Interface sintética com mapa real é a combinação que
importa: a interface é a parte fácil de imitar, o terreno não.
"""

from pathlib import Path

import numpy as np
import pytest

from lolqueue.vision.minimap import (
    MAX_SIDE_FRACTION,
    Minimap,
    locate,
    search_area,
)
from lolqueue.vision.window import Rect

FIXTURE = Path(__file__).parent / "fixtures" / "minimap_sample.png"

#: O caso que originou o bug: jogo em janela, deslocado, numa tela
#: maior e mais larga que ele.
JOGO = Rect(859, 1, 1920, 1080)


@pytest.fixture(scope="module")
def mapa() -> np.ndarray:
    from PIL import Image

    return np.array(Image.open(FIXTURE).convert("RGB"))


def cena(area: Rect, mapa: np.ndarray, margem_x: int, margem_y: int) -> np.ndarray:
    """Interface escura com o minimapa colado a uma margem do canto."""
    rng = np.random.default_rng(11)
    frame = np.full((area.height, area.width, 3), 12, np.uint8)
    frame += rng.integers(0, 6, frame.shape, dtype=np.uint8)
    lado = mapa.shape[0]
    y = area.height - lado - margem_y
    x = area.width - lado - margem_x
    frame[y : y + lado, x : x + lado] = mapa
    return frame


def test_the_search_area_hugs_the_bottom_right_corner():
    area = search_area(JOGO)
    assert (area.right, area.bottom) == (JOGO.right, JOGO.bottom)
    assert area.width == area.height


@pytest.mark.parametrize("margem", [(0, 0), (12, 18), (30, 25), (5, 40)])
def test_the_minimap_is_found_whatever_the_margin(mapa, margem):
    """A margem que o jogo deixa varia, e não pode ser adivinhada.

    A primeira versão desta medição partia do canto da tela e falhava
    em toda margem diferente de zero.
    """
    area = search_area(JOGO)
    got = locate(cena(area, mapa, *margem), area)
    assert got is not None
    assert abs(got.rect.width - mapa.shape[0]) <= 3
    assert abs(got.rect.x - (area.x + area.width - mapa.shape[0] - margem[0])) <= 3
    assert abs(got.rect.y - (area.y + area.height - mapa.shape[0] - margem[1])) <= 3


def test_dark_lanes_inside_the_map_do_not_shrink_it(mapa):
    """Rio e nevoeiro derrubam colunas inteiras e não são a borda.

    Com o corte preso ao topo da escala, essas colunas ficavam de fora
    e o minimapa era medido menor do que é.
    """
    area = search_area(JOGO)
    escurecido = mapa.copy()
    escurecido[:, 40:70] = escurecido[:, 40:70] // 3
    got = locate(cena(area, escurecido, 10, 10), area)
    assert got is not None
    assert abs(got.rect.width - mapa.shape[0]) <= 6


@pytest.mark.parametrize(
    "nome,frame",
    [
        ("tela preta", np.zeros((486, 486, 3), np.uint8)),
        ("cor chapada", np.full((486, 486, 3), 128, np.uint8)),
        (
            "gradiente de carregamento",
            np.tile(np.linspace(0, 120, 486, dtype=np.uint8)[None, :, None], (486, 1, 3)),
        ),
    ],
)
def test_scenes_without_a_map_are_refused(nome, frame):
    """Calar é melhor que apontar para o lugar errado."""
    assert locate(frame, search_area(JOGO)) is None


def test_a_lone_hud_element_is_not_a_minimap():
    frame = np.full((486, 486, 3), 12, np.uint8)
    frame[100:140, 100:140] = 200
    assert locate(frame, search_area(JOGO)) is None


def test_a_tall_block_is_not_a_minimap():
    """O minimapa é quadrado; medir dois lados diferentes é sintoma."""
    rng = np.random.default_rng(5)
    frame = np.full((486, 486, 3), 12, np.uint8)
    frame[50:450, 20:200] = rng.integers(0, 255, (400, 180, 3), dtype=np.uint8)
    assert locate(frame, search_area(JOGO)) is None


def test_an_oversized_block_is_refused(mapa):
    """Maior que o maior minimapa possível é medida contaminada."""
    area = search_area(JOGO)
    frame = np.full((area.height, area.width, 3), 12, np.uint8)
    lado = int(MAX_SIDE_FRACTION * JOGO.height) + 60
    from PIL import Image

    grande = np.array(Image.fromarray(mapa).resize((lado, lado)))
    frame[-lado:, -lado:] = grande
    assert locate(frame, area) is None


def test_map_coordinates_are_anchored_on_the_blue_base():
    """(0,1) é a base azul e (1,0) a vermelha, gire-se ou não o mapa."""
    plano = Minimap(Rect(0, 0, 300, 300), flipped=False)
    assert plano.to_map(0, 300) == (0.0, 1.0)
    assert plano.to_map(300, 0) == (1.0, 0.0)
    assert plano.to_map(150, 150) == (0.5, 0.5)


def test_flipping_the_minimap_does_not_move_the_bases():
    """Com `FlipMiniMap`, o mesmo pixel é o canto oposto do mapa.

    Sem tratar isto, todo aviso sairia com a rota trocada para quem
    usa a opção.
    """
    girado = Minimap(Rect(0, 0, 300, 300), flipped=True)
    assert girado.to_map(0, 300) == (1.0, 0.0)
    assert girado.to_map(300, 0) == (0.0, 1.0)
    assert girado.to_map(150, 150) == (0.5, 0.5)


def test_coordinates_never_escape_the_map(mapa):
    plano = Minimap(Rect(0, 0, 300, 300))
    assert plano.to_map(-50, 900) == (0.0, 1.0)
