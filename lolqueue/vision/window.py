"""Onde a janela do jogo está na tela.

Este módulo existe por causa de um bug concreto: é tentador calcular a
posição do minimapa a partir do tamanho da *tela*, porque o minimapa
fica "no canto inferior direito". Isso só funciona quando o jogo ocupa
a tela inteira. Nesta máquina, por exemplo, a tela tem 3440x1440 e o
jogo roda numa janela de 1920x1080 deslocada 859px para a direita: o
canto inferior direito da tela cai fora do jogo, e quem mira ali
fotografa área morta. A âncora correta é sempre o retângulo-cliente da
janela do jogo, convertido para coordenadas de tela.

A segunda armadilha é o título. O cliente (loja, fila, seleção de
campeões) e a partida se chamam ambos "League of Legends"; procurar
pelo título acha o cliente e aponta a câmera para a lista de amigos.
O que separa os dois é a classe da janela: a partida é
`RiotWindowClass`, o cliente é `RCLIENT`.

Tudo aqui é dividido em duas metades: funções puras que decidem (e que
os testes exercitam sem Windows nenhum) e funções que conversam com a
API do Windows via ctypes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

#: Classe da janela da partida em si. É o que queremos fotografar.
GAME_CLASS = "RiotWindowClass"

#: Classe da janela do cliente. Tem o mesmo título da partida e por
#: isso precisa ser reconhecida para ser descartada de propósito.
CLIENT_CLASS = "RCLIENT"

#: Abaixo disto não é partida: é janela recém-criada, minimizada ou
#: algum artefato. O menor modo gráfico do LoL é bem maior que isso.
MIN_GAME_SIDE = 640


@dataclass(frozen=True)
class Rect:
    """Uma região em coordenadas de tela, em pixels físicos."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def is_usable(self) -> bool:
        return self.width >= MIN_GAME_SIDE and self.height >= MIN_GAME_SIDE


@dataclass(frozen=True)
class WindowInfo:
    """O mínimo que precisamos saber de uma janela para escolher uma."""

    handle: int
    class_name: str
    title: str


def pick_game_window(windows: Iterable[WindowInfo]) -> WindowInfo | None:
    """A janela da partida entre todas as janelas visíveis.

    Pura de propósito: a escolha é a parte que erra, então é a parte
    que os testes precisam alcançar sem um jogo aberto. Casa pela
    classe e ignora o título justamente porque o título mente.
    """
    for window in windows:
        if window.class_name == GAME_CLASS:
            return window
    return None


def has_client_only(windows: Sequence[WindowInfo]) -> bool:
    """Verdadeiro quando o cliente está aberto mas a partida não.

    Serve para a camada de cima dizer "aguardando a partida" em vez de
    "jogo não encontrado", que são situações diferentes para o usuário.
    """
    if pick_game_window(windows) is not None:
        return False
    return any(window.class_name == CLIENT_CLASS for window in windows)


# --- daqui para baixo, Windows de verdade ------------------------------


def _user32():
    import ctypes

    return ctypes.windll.user32


def declare_dpi_awareness() -> None:
    """Pede coordenadas em pixels físicos, sem escalar.

    Sem isto, num monitor a 150% o Windows mente sobre o tamanho da
    janela e todo recorte sai deslocado. A chamada falha de propósito
    quando alguém já declarou a política do processo — o Qt declara na
    inicialização — e falhar aí é o resultado certo, não um erro: quem
    já declarou declarou algo pelo menos tão bom quanto isto.
    """
    import ctypes

    try:
        # -4 = PER_MONITOR_AWARE_V2, o único que acerta em multi-monitor
        # com escalas diferentes, que é o caso de quem joga em ultrawide
        # com um segundo monitor.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def enumerate_windows() -> list[WindowInfo]:
    """Todas as janelas visíveis com título, na ordem do Windows."""
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = _user32()
    found: list[WindowInfo] = []

    def visit(handle, _param):
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, title, length + 1)
        klass = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, klass, 256)
        found.append(WindowInfo(int(handle), klass.value, title.value))
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(callback(visit), 0)
    return found


def client_rect(handle: int) -> Rect | None:
    """A área útil da janela, já em coordenadas de tela.

    `GetClientRect` devolve a área sem bordas nem barra de título, mas
    com a origem no canto da própria janela; `ClientToScreen` traduz
    essa origem para a tela. É a combinação dos dois que dá o
    retângulo onde o jogo realmente desenha.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = _user32()
    box = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(handle), ctypes.byref(box)):
        return None
    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(wintypes.HWND(handle), ctypes.byref(origin)):
        return None
    width = int(box.right - box.left)
    height = int(box.bottom - box.top)
    if width <= 0 or height <= 0:
        return None
    return Rect(int(origin.x), int(origin.y), width, height)


#: Assinaturas injetáveis: os testes trocam estas duas por funções que
#: devolvem cenários fixos, e assim exercitam `viewport` inteiro sem
#: Windows, sem jogo aberto e sem tela.
Enumerator = Callable[[], list[WindowInfo]]
Measurer = Callable[[int], "Rect | None"]


def viewport(
    enumerate_fn: Enumerator = enumerate_windows,
    measure_fn: Measurer = client_rect,
) -> Rect | None:
    """Onde o jogo desenha, ou `None` se não há partida na tela.

    Devolve `None` também para janela pequena demais: durante a
    criação da janela o Windows chega a informar tamanhos absurdos por
    um instante, e recortar em cima disso produz lixo.
    """
    window = pick_game_window(enumerate_fn())
    if window is None:
        return None
    rect = measure_fn(window.handle)
    if rect is None or not rect.is_usable():
        return None
    return rect
