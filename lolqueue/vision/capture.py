"""Fotografar um pedaço da tela, muitas vezes por segundo, sem vazar.

São duas estratégias atrás de uma fachada só, `ScreenGrabber`:

* **Desktop Duplication** (`duplication.py`), a primária. Lê o quadro
  que a GPU apresenta, então enxerga o jogo também em fullscreen
  exclusivo.
* **GDI** (`GdiGrabber`, aqui), o plano B. Lê o desktop composto. É
  cego em fullscreen exclusivo — devolve um retângulo perfeitamente
  preto, que foi o bug que deixou o aviso de jungler mudo por várias
  partidas — mas funciona onde o DXGI não existe: máquina virtual sem
  GPU, sessão remota, driver sem suporte a duplicação.

O GDI continua sendo ctypes cru, e não uma biblioteca de captura,
porque o app é distribuído como executável único: cada dependência
nova entra inteira no build. GDI já está no Windows.

O detalhe que mais importa no GDI não é velocidade, é higiene. Um
`CreateCompatibleBitmap` sem o `DeleteObject` correspondente vaza um
handle GDI por quadro; a dez quadros por segundo isso são 36 mil
handles numa partida, e o Windows começa a recusar desenhar em
*qualquer* programa muito antes disso — a tela do usuário fica preta e
a culpa parece ser do jogo. Por isso o grabber é uma classe com tempo
de vida explícito: aloca uma vez por tamanho de região, reaproveita
enquanto a região não muda e devolve tudo no `close`.

As duas estratégias devolvem exatamente o mesmo formato — RGB uint8,
`(altura, largura, 3)`, recortado no `Rect` pedido — e devolvem `None`
em vez de levantar. É o que permite trocar uma pela outra sem que o
`JungleWatcher` saiba de nada.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    import numpy as np

from .window import Rect

#: BitBlt: cópia direta, sem raster op.
SRCCOPY = 0x00CC0020

#: BitBlt: inclui janelas com camada (overlays). Fica documentado e
#: deliberadamente **fora** do BitBlt logo abaixo, porque o remédio
#: era pior que a doença: CAPTUREBLT obriga o Windows a redesenhar a
#: tela inteira a cada cópia, e um jogo em tela cheia exclusiva perde
#: a exclusividade quando isso acontece — o League minimizava
#: sozinho, de novo e de novo, a cinco capturas por segundo. O que se
#: ganhava eram overlays (Discord, GeForce) aparecendo no quadro,
#: coisa que a detecção do minimapa não usa para nada.
CAPTUREBLT = 0x40000000

#: GetDIBits: pedir os pixels já decodificados, sem paleta.
DIB_RGB_COLORS = 0


#: Quantas tentativas o DXGI ganha para entregar o primeiro quadro
#: antes de a fachada desistir dele. A 5 quadros por segundo isso são
#: quatro segundos: sobra para a duplicação aquecer e para uma troca de
#: modo de vídeo terminar, e é pouco o bastante para o usuário não
#: passar a partida inteira sem aviso caso o DXGI esteja quebrado.
DUPLICATION_TRIAL_GRABS = 20


#: Quanto tempo o GDI tem para provar que dá conta antes de o DXGI
#: ganhar uma segunda chance. Só corre enquanto o GDI está devolvendo
#: preto — e preto no plano B, com o jogo aberto, é o sintoma exato da
#: tela cheia exclusiva. Nesse estado insistir no DXGI não é teimosia:
#: é a única estratégia que enxerga, e desistir dela para sempre por
#: causa de um tropeço na troca de modo de vídeo custa a partida
#: inteira. Quando o GDI está enxergando, nada disto acontece.
DUPLICATION_RETRY_SECONDS = 15.0


def _looks_black(frame) -> bool:
    """Se o quadro não tem um único pixel aceso — ou nem existe."""
    if frame is None:
        return True
    try:
        return not frame.any()
    except Exception:  # pragma: no cover - quadro que não é ndarray
        return False


class GdiGrabber:
    """Captura repetida de regiões da tela, reaproveitando os recursos.

    Não é seguro para uso simultâneo em várias threads: o buffer é um
    só, de propósito, para não realocar a cada quadro. Quem usa mantém
    um grabber por thread.
    """

    def __init__(self) -> None:
        self._size: tuple[int, int] | None = None
        self._screen_dc = None
        self._memory_dc = None
        self._bitmap = None
        self._previous = None
        self._buffer = None
        self._closed = False

    # -- ciclo de vida --------------------------------------------------

    def _ensure(self, width: int, height: int) -> None:
        """Garante recursos GDI do tamanho pedido, realocando se mudou."""
        import ctypes

        if self._size == (width, height) and self._bitmap:
            return
        self._release_gdi()

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # DC da tela inteira (handle 0 = desktop).
        self._screen_dc = user32.GetDC(0)
        if not self._screen_dc:
            raise OSError("não foi possível obter o contexto da tela")
        self._memory_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        self._bitmap = gdi32.CreateCompatibleBitmap(self._screen_dc, width, height)
        if not self._memory_dc or not self._bitmap:
            self._release_gdi()
            raise OSError("não foi possível alocar o bitmap de captura")
        self._previous = gdi32.SelectObject(self._memory_dc, self._bitmap)
        self._buffer = ctypes.create_string_buffer(width * height * 4)
        self._size = (width, height)

    def _release_gdi(self) -> None:
        """Devolve ao Windows tudo que foi alocado. Idempotente."""
        import ctypes

        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        if self._memory_dc and self._previous:
            gdi32.SelectObject(self._memory_dc, self._previous)
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        if self._memory_dc:
            gdi32.DeleteDC(self._memory_dc)
        if self._screen_dc:
            user32.ReleaseDC(0, self._screen_dc)
        self._screen_dc = self._memory_dc = self._bitmap = self._previous = None
        self._buffer = None
        self._size = None

    def close(self) -> None:
        self._release_gdi()
        self._closed = True

    def __enter__(self) -> "GdiGrabber":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - rede de segurança
        # Não substitui o `close`; existe só para que um esquecimento
        # não vire um vazamento permanente.
        try:
            self._release_gdi()
        except Exception:
            pass

    # -- captura --------------------------------------------------------

    def grab(self, rect: Rect) -> "np.ndarray | None":
        """Os pixels de `rect` como RGB (altura, largura, 3), ou `None`.

        Devolve `None` em vez de levantar quando a captura falha, e
        isso é intencional: falha aqui é rotina, não excepcional — o
        jogo pode ter fechado, a região pode ter saído da tela, o
        usuário pode ter bloqueado a sessão. Quem chama trata como
        "sem quadro agora" e tenta de novo no próximo tique.
        """
        import ctypes

        import numpy as np

        if self._closed or rect.width <= 0 or rect.height <= 0:
            return None

        try:
            self._ensure(rect.width, rect.height)
        except OSError:
            return None

        gdi32 = ctypes.windll.gdi32
        copied = gdi32.BitBlt(
            self._memory_dc,
            0,
            0,
            rect.width,
            rect.height,
            self._screen_dc,
            rect.x,
            rect.y,
            SRCCOPY,
        )
        if not copied:
            return None

        header = _bitmap_info(rect.width, rect.height)
        lines = gdi32.GetDIBits(
            self._memory_dc,
            self._bitmap,
            0,
            rect.height,
            self._buffer,
            ctypes.byref(header),
            DIB_RGB_COLORS,
        )
        if lines != rect.height:
            return None

        raw = np.frombuffer(self._buffer, dtype=np.uint8, count=rect.width * rect.height * 4)
        frame = raw.reshape((rect.height, rect.width, 4))
        # GDI entrega BGRA; o resto do código pensa em RGB. A cópia é
        # necessária: o buffer é reaproveitado no próximo quadro e uma
        # view viraria dado corrompido na mão de quem guardou.
        return frame[:, :, 2::-1].copy()


class ScreenGrabber:
    """A captura vista de fora: escolhe a estratégia e não conta a ninguém.

    A escolha é feita na primeira captura, não na construção, por dois
    motivos práticos. Primeiro, montar um dispositivo D3D11 na thread
    da interface seria trabalho jogado fora quando não há partida.
    Segundo, o `Rect` pedido é o que diz *qual monitor* duplicar, e ele
    só existe na hora da captura.

    A degradação para GDI acontece em dois casos: quando montar o
    dispositivo falha de vez (`DuplicationUnavailable` — máquina
    virtual, driver antigo) e quando o DXGI monta mas não entrega um
    único quadro em `DUPLICATION_TRIAL_GRABS` tentativas. O segundo
    caso existe porque "monta mas nunca entrega" é indistinguível de
    estar quebrado.

    Ela já foi definitiva, e era essa a falha que impedia o app de
    funcionar em tela cheia exclusiva. Entrar em tela cheia derruba a
    duplicação (`ACCESS_LOST`) e a troca de modo de vídeo leva alguns
    quadros; quando isso pega o DXGI antes do primeiro quadro provado,
    a fachada desistia dele para sempre e caía no GDI — que, por cima
    de um jogo em tela cheia exclusiva, devolve preto para sempre. O
    jogador ficava cego exatamente no modo em que só o DXGI enxerga, e
    a única saída oferecida era sair da tela cheia.

    Por isso a desistência agora é revogável, mas só sob a condição que
    importa: o GDI também estar devolvendo preto. Nesse estado — e só
    nele — o DXGI ganha uma tentativa nova a cada
    `DUPLICATION_RETRY_SECONDS`. Com o GDI enxergando, a desistência
    continua valendo e nada se gasta tentando de novo. Uma vez que o
    DXGI entregou um quadro, ele é a estratégia até o `close`: falhas
    depois disso são transitórias e o próprio grabber já as trata.

    Como o GDI, um objeto por thread.
    """

    def __init__(
        self,
        prefer_duplication: bool = True,
        duplication_factory=None,
        gdi_factory=None,
        clock=None,
    ) -> None:
        # As fábricas entram pelo construtor para que os testes possam
        # exercitar a escolha inteira sem GPU e sem tela. O relógio entra
        # pelo mesmo motivo: sem ele, testar a segunda chance do DXGI
        # exigiria esperar quinze segundos de verdade.
        import time

        self._prefer = prefer_duplication
        self._new_duplication = duplication_factory or _default_duplication
        self._new_gdi = gdi_factory or GdiGrabber
        self._clock = clock or time.monotonic
        self._duplication = None
        self._gdi = None
        self._attempts = 0
        self._proved = False
        self._gave_up = not prefer_duplication
        self._gave_up_at = None
        self._blind_gdi = False
        self._closed = False

    @property
    def strategy(self) -> str:
        """Qual estratégia está em uso agora: `"dxgi"` ou `"gdi"`."""
        return "gdi" if self._gave_up else "dxgi"

    def _give_up(self) -> None:
        """Desiste do DXGI agora, guardando a hora para a segunda chance."""
        self._gave_up = True
        self._gave_up_at = self._clock()
        self._close_duplication()

    def _duplication_grab(self, rect: Rect) -> "np.ndarray | None":
        """Tenta o DXGI e devolve `None` quando é hora de desistir dele."""
        if self._duplication is None:
            try:
                self._duplication = self._new_duplication()
            except Exception:
                # Inclui `DuplicationUnavailable`: esta máquina não
                # duplica o desktop. Pode ser também o instante em que o
                # jogo toma a tela para si — daí a segunda chance logo
                # abaixo, condicionada ao GDI estar cego.
                self._give_up()
                return None
        quadro = self._duplication.grab(rect)
        if quadro is not None:
            self._proved = True
            return quadro
        if not self._proved:
            self._attempts += 1
            if self._attempts >= DUPLICATION_TRIAL_GRABS:
                self._give_up()
        return None

    def _retry_is_due(self) -> bool:
        """Se vale gastar uma tentativa nova no DXGI.

        Duas condições, e as duas precisam valer. A primeira é o GDI
        estar devolvendo preto: enquanto o plano B enxerga, trocar de
        estratégia só criaria oscilação sem ganho. A segunda é o tempo
        de espera, para que uma partida inteira em tela cheia não vire
        uma fila de montagens de dispositivo D3D11 a cinco por segundo.
        """
        if not self._prefer or not self._blind_gdi or self._gave_up_at is None:
            return False
        return self._clock() - self._gave_up_at >= DUPLICATION_RETRY_SECONDS

    def grab(self, rect: Rect) -> "np.ndarray | None":
        """Os pixels de `rect` como RGB (altura, largura, 3), ou `None`."""
        if self._closed or rect.width <= 0 or rect.height <= 0:
            return None
        if self._gave_up and self._retry_is_due():
            # A cota de tentativas recomeça: a anterior pode ter sido
            # gasta inteira na troca de modo de vídeo.
            self._gave_up = False
            self._gave_up_at = None
            self._attempts = 0
        if not self._gave_up:
            quadro = self._duplication_grab(rect)
            if quadro is not None:
                self._blind_gdi = False
                return quadro
            if not self._gave_up:
                return None
            # Acabou de desistir: o GDI ainda pode salvar este quadro.
        if self._gdi is None:
            self._gdi = self._new_gdi()
        quadro = self._gdi.grab(rect)
        # Preto no plano B, com o jogo aberto, é o sintoma da tela cheia
        # exclusiva — e é o que libera a segunda chance do DXGI.
        self._blind_gdi = _looks_black(quadro)
        return quadro

    # -- ciclo de vida --------------------------------------------------

    def _close_duplication(self) -> None:
        alvo = self._duplication
        self._duplication = None
        if alvo is not None:
            try:
                alvo.close()
            except Exception:
                pass

    def close(self) -> None:
        self._closed = True
        self._close_duplication()
        alvo = self._gdi
        self._gdi = None
        if alvo is not None:
            try:
                alvo.close()
            except Exception:
                pass

    def __enter__(self) -> "ScreenGrabber":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _default_duplication():
    """Importa o DXGI só quando ele é realmente tentado.

    O `duplication` monta estruturas ctypes na importação; num Windows
    sem `d3d11.dll` isso continua funcionando, mas não há motivo para
    pagar o custo em quem já sabe que vai usar GDI.
    """
    from .duplication import DuplicationGrabber

    grabber = DuplicationGrabber()
    try:
        # `prepare` na fábrica, e não na primeira captura, para que
        # `DuplicationUnavailable` chegue a quem sabe cair no GDI. Sem
        # isto a exceção morreria dentro do `grab`, que engole tudo, e a
        # máquina sem GPU passaria quatro segundos capturando nada.
        grabber.prepare()
    except Exception:
        grabber.close()
        raise
    return grabber


def _bitmap_info(width: int, height: int):
    """Cabeçalho pedindo 32 bits por pixel, de cima para baixo.

    A altura negativa é o que inverte a ordem das linhas: bitmaps do
    Windows nascem de baixo para cima, e sem isso toda imagem sai de
    cabeça para baixo.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    return info
