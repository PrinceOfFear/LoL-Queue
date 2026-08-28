"""Achar o minimapa dentro da imagem do jogo.

A tentação é calcular: "o minimapa é tantos por cento da altura, no
canto inferior direito". Não dá. O tamanho depende do `MinimapScale`
do `game.cfg`, que é um controle deslizante que cada jogador mexe, e a
margem depende da escala da interface. Qualquer constante acerta numa
máquina e erra em todas as outras.

Então este módulo mede em vez de supor. O minimapa é uma fotografia do
terreno: cheio de variação de cor e de brilho. O que existe ao redor
dele é interface — preta, chapada, previsível. Percorrendo a variação
por coluna e por linha, a fronteira entre os dois aparece como um
degrau, e é esse degrau que define a borda. Medido uma vez, o
resultado vale até a janela mudar de tamanho.

A medição ainda é conferida contra duas coisas que sabemos de
antemão: o minimapa é quadrado, e ele encosta no canto inferior
direito. Uma leitura que viole qualquer das duas é descartada — é
melhor não avisar nada do que avisar sobre o lugar errado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

from .window import Rect

#: Fração do lado do jogo onde vale a pena procurar. O minimapa maior
#: que o LoL desenha fica perto de 30% da altura; 45% dá folga para a
#: margem e para escalas de interface grandes sem arrastar meia tela.
SEARCH_FRACTION = 0.45

#: O minimapa nunca é menor que isto em relação à altura do jogo, nem
#: maior. Serve para rejeitar leitura absurda vinda de tela de
#: carregamento ou de quadro capturado no meio de uma transição.
MIN_SIDE_FRACTION = 0.12
MAX_SIDE_FRACTION = 0.34

#: Onde cortar, medido como fração do caminho entre o fundo e o
#: conteúdo — não como fração do conteúdo. A diferença é decisiva: a
#: interface ao redor marca variação perto de 1 e o miolo do minimapa
#: passa de 50, mas colunas legítimas do minimapa descem a 12 quando
#: caem numa faixa de nevoeiro. Um corte preso ao topo da escala
#: amputa justamente essas colunas e encolhe o minimapa; ancorado no
#: fundo, ele fica bem abaixo delas e ainda muito acima da interface.
EDGE_LEVEL = 0.15
FLOOR_PERCENTILE = 10
CONTENT_PERCENTILE = 90

#: Lacuna tolerada dentro do minimapa, em fração do lado da busca. O
#: mapa tem faixas escuras — rio, nevoeiro — que podem afundar
#: algumas colunas abaixo do corte sem que ali acabe o minimapa.
MAX_GAP_FRACTION = 0.05

#: Diferença tolerada entre o lado medido na horizontal e na vertical.
#: São medições independentes de um quadrado, então divergir muito
#: significa que uma delas pegou interface junto.
SQUARENESS_TOLERANCE = 0.08

#: Piso de variação de cor para aceitar que a região é mesmo terreno.
#: Uma tela de carregamento ou um quadro preto passa no teste do
#: degrau e falha neste.
MIN_COLOR_SPREAD = 18.0


@dataclass(frozen=True)
class Minimap:
    """O minimapa localizado, em coordenadas de tela."""

    rect: Rect
    #: Verdadeiro quando o jogador ativou `FlipMiniMap`, e o mapa está
    #: girado 180° para a base dele ficar sempre embaixo à esquerda.
    flipped: bool = False

    def to_map(self, x: float, y: float) -> tuple[float, float]:
        """Pixel dentro do minimapa para coordenada do mapa em 0..1.

        A referência é sempre a mesma, gire o jogador o minimapa ou
        não: (0, 1) é a base azul, no canto inferior esquerdo, e
        (1, 0) é a base vermelha. Normalizar aqui é o que permite às
        zonas nomeadas serem escritas uma vez só.
        """
        side = max(self.rect.width, 1)
        mx = min(max(x / side, 0.0), 1.0)
        my = min(max(y / side, 0.0), 1.0)
        if self.flipped:
            mx, my = 1.0 - mx, 1.0 - my
        return mx, my


def search_area(viewport: Rect) -> Rect:
    """O canto inferior direito do jogo, onde o minimapa mora.

    Recortar antes de medir não é só economia: quanto menos interface
    entra na conta, mais limpo fica o degrau que separa o minimapa do
    resto.
    """
    side = int(min(viewport.width, viewport.height) * SEARCH_FRACTION)
    side = max(side, 1)
    return Rect(viewport.right - side, viewport.bottom - side, side, side)


def _content_profile(gray: "np.ndarray", axis: int) -> "np.ndarray":
    """Quanta variação existe em cada linha (axis=1) ou coluna (axis=0)."""
    return gray.std(axis=axis)


def _content_span(profile: "np.ndarray", max_gap: int) -> tuple[int, int] | None:
    """O maior trecho contínuo de conteúdo do perfil, como (início, fim).

    Antes isto varria do fim para o começo, apostando que o minimapa
    encostava no canto da tela. Não encosta: o jogo deixa uma margem,
    e a aposta fazia a medição desistir sempre que havia interface
    depois do minimapa. Procurar o maior bloco contínuo não depende de
    onde o bloco está, o que também torna a medição imune a um ícone
    solto de interface no meio da área de busca — ele forma um bloco
    curto, e o do minimapa é sempre o mais longo.
    """
    import numpy as np

    if profile.size == 0:
        return None
    floor = float(np.percentile(profile, FLOOR_PERCENTILE))
    peak = float(np.percentile(profile, CONTENT_PERCENTILE))
    if peak - floor <= 0.0:
        return None
    filled = profile >= floor + (peak - floor) * EDGE_LEVEL

    best: tuple[int, int] | None = None
    run_start: int | None = None
    gap = 0
    for index, is_filled in enumerate(filled):
        if is_filled:
            if run_start is None:
                run_start = index
            gap = 0
            continue
        if run_start is None:
            continue
        gap += 1
        if gap > max_gap:
            stop = index - gap + 1
            if best is None or stop - run_start > best[1] - best[0]:
                best = (run_start, stop)
            run_start = None
            gap = 0
    if run_start is not None:
        stop = len(filled) - gap
        if best is None or stop - run_start > best[1] - best[0]:
            best = (run_start, stop)
    return best


def locate(frame: "np.ndarray", area: Rect, flipped: bool = False) -> Minimap | None:
    """Onde está o minimapa dentro de `frame`, ou `None` se não deu.

    `frame` são os pixels de `area`, e o retângulo devolvido já vem em
    coordenadas de tela para poder ser recortado direto no próximo
    quadro.
    """
    import numpy as np

    if frame is None or frame.ndim != 3 or frame.shape[0] < 8:
        return None

    gray = frame.mean(axis=2)
    if float(gray.std()) < MIN_COLOR_SPREAD:
        return None

    max_gap = max(int(min(frame.shape[:2]) * MAX_GAP_FRACTION), 1)
    horizontal = _content_span(_content_profile(gray, axis=0), max_gap)
    vertical = _content_span(_content_profile(gray, axis=1), max_gap)
    if horizontal is None or vertical is None:
        return None

    left, right = horizontal
    top, bottom = vertical
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    # Duas medidas independentes do mesmo quadrado precisam concordar.
    bigger = max(width, height)
    if abs(width - height) / bigger > SQUARENESS_TOLERANCE:
        return None
    side = min(width, height)

    limit = frame.shape[0] / SEARCH_FRACTION  # altura aproximada do jogo
    if not (MIN_SIDE_FRACTION * limit <= side <= MAX_SIDE_FRACTION * limit):
        return None

    # Ancorar no canto medido, não no canto da tela: agora que as
    # quatro bordas são conhecidas, a margem que o jogo deixa é dado
    # observado e não precisa mais ser adivinhada.
    return Minimap(
        Rect(area.x + left, area.y + top, side, side),
        flipped=flipped,
    )
