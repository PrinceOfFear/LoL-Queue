"""A escolha da janela do jogo.

O erro que estes testes existem para impedir é específico: o cliente e
a partida se chamam ambos "League of Legends", e mirar pelo título faz
o app fotografar a lista de amigos achando que é o mapa.
"""

import pytest

from lolqueue.vision.window import (
    CLIENT_CLASS,
    GAME_CLASS,
    MIN_GAME_SIDE,
    Rect,
    WindowInfo,
    has_client_only,
    pick_game_window,
    viewport,
)

JOGO = WindowInfo(handle=1, class_name=GAME_CLASS, title="League of Legends")
CLIENTE = WindowInfo(handle=2, class_name=CLIENT_CLASS, title="League of Legends")
NAVEGADOR = WindowInfo(handle=3, class_name="Chrome_WidgetWin_1", title="League of Legends - wiki")


def test_the_client_is_not_mistaken_for_the_game():
    """Mesmo título, janelas diferentes: só a classe separa as duas."""
    assert pick_game_window([CLIENTE]) is None
    assert pick_game_window([CLIENTE, JOGO]) is JOGO


def test_a_browser_tab_named_after_the_game_is_ignored():
    assert pick_game_window([NAVEGADOR]) is None


def test_client_without_game_is_its_own_situation():
    """Esperar a partida começar não é o mesmo que não achar o jogo."""
    assert has_client_only([CLIENTE]) is True
    assert has_client_only([CLIENTE, JOGO]) is False
    assert has_client_only([]) is False


def test_the_viewport_comes_from_the_client_area():
    """A âncora é a janela, nunca a tela.

    O caso real que motivou isto: tela de 3440x1440 com o jogo numa
    janela de 1920x1080 deslocada para a direita. Quem parte da tela
    mira fora do jogo.
    """
    medido = Rect(859, 1, 1920, 1080)
    got = viewport(lambda: [CLIENTE, JOGO], lambda handle: medido)
    assert got == medido
    assert got.right == 2779 and got.bottom == 1081


def test_no_game_means_no_viewport():
    assert viewport(lambda: [CLIENTE], lambda handle: Rect(0, 0, 1920, 1080)) is None


def test_a_window_too_small_to_be_a_game_is_refused():
    """O Windows informa tamanhos absurdos enquanto a janela nasce."""
    pequena = Rect(0, 0, MIN_GAME_SIDE - 1, MIN_GAME_SIDE - 1)
    assert viewport(lambda: [JOGO], lambda handle: pequena) is None


def test_an_unmeasurable_window_is_refused():
    assert viewport(lambda: [JOGO], lambda handle: None) is None


@pytest.mark.parametrize(
    "rect,esperado",
    [
        (Rect(0, 0, 1920, 1080), True),
        (Rect(0, 0, 640, 640), True),
        (Rect(0, 0, 1920, 100), False),
    ],
)
def test_usable_sizes(rect, esperado):
    assert rect.is_usable() is esperado
