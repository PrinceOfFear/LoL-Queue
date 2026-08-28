"""Fotografar a tela quando o GDI é cego: fullscreen exclusivo.

O `ScreenGrabber` de `capture.py` lê o *desktop composto* (`GetDC(0)` +
`BitBlt`). Isso funciona com o jogo em janela ou em janela-sem-borda,
porque nesses modos quem desenha a tela final é o compositor do Windows
e o desktop contém a imagem do jogo. Em **fullscreen exclusivo**
(`game.cfg` → `[General] WindowMode=0`) o jogo toma a saída de vídeo
para si e o compositor sai do caminho: o desktop deixa de conter a
imagem, e todo `BitBlt` devolve um retângulo perfeitamente preto — foi
exatamente o sintoma que deixou o aviso de jungler mudo (`frame.mean()`
== 0.0 em todo quadro). Testado ao vivo: `BitBlt` com e sem
`CAPTUREBLT`, `PrintWindow` com e sem `PW_RENDERFULLCONTENT`, todos
zeros.

A Desktop Duplication API do DXGI lê um degrau abaixo: ela entrega o
quadro que a GPU está *apresentando* na saída, inclusive quando quem
apresenta é um jogo em fullscreen exclusivo. É a única forma suportada
de capturar essa tela sem injetar código no processo do jogo — o que
seria indistinguível de um cheat para o anticheat da Riot.

Tudo aqui é ctypes puro, com as vtables COM montadas à mão, pelo mesmo
motivo que o resto do projeto fala com GDI e MCI por ctypes: o app é
distribuído como executável único e cada dependência nova entra inteira
no build. `comtypes` traria um gerador de código e a `d3dshot` traria
uma cadeia de dependências, para chamar sete métodos.

Regras de higiene que este módulo respeita porque a API não perdoa:

* `ReleaseFrame` **sempre** que `AcquireNextFrame` deu certo, mesmo que
  a cópia falhe no meio. Segurar um quadro faz a próxima aquisição
  falhar com `DXGI_ERROR_INVALID_CALL` para sempre.
* `DXGI_ERROR_WAIT_TIMEOUT` não é erro: significa "nada mudou na tela
  desde o último quadro". Devolver `None` aí faria a vigilância piscar
  em toda tela parada; devolvemos o último quadro válido.
* `DXGI_ERROR_ACCESS_LOST` acontece em troca de modo de vídeo, UAC,
  Ctrl+Alt+Del e troca de usuário. A duplicação morre e precisa ser
  recriada — mas na *próxima* chamada, não em um laço aqui dentro, que
  seguraria a thread durante uma transição que pode levar segundos.

Nada levanta exceção para fora: erro vira `None`, como no GDI.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    import numpy as np

from .window import Rect

# --- constantes da API -------------------------------------------------

#: HRESULTs que precisam de tratamento próprio, não de "deu erro".
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_NOT_FOUND = 0x887A0002

#: `D3D_DRIVER_TYPE_HARDWARE`; sem GPU não há duplicação e o `capture`
#: cai no GDI.
D3D_DRIVER_TYPE_HARDWARE = 1

#: `D3D11_SDK_VERSION`. Fixo desde o Windows 7.
D3D11_SDK_VERSION = 7

#: `D3D11_CREATE_DEVICE_BGRA_SUPPORT`. A duplicação sempre entrega
#: B8G8R8A8, então pedir o suporte explicitamente evita recusa em
#: drivers antigos.
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20

DXGI_FORMAT_B8G8R8A8_UNORM = 87
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1

#: Quanto esperar por um quadro novo. Zero devolveria `WAIT_TIMEOUT` em
#: toda tela parada e nos obrigaria a servir cache o tempo todo; 120 ms
#: é menos que o intervalo do vigia (200 ms a 5 fps) e ainda dá tempo
#: para a GPU apresentar um quadro de jogo.
ACQUIRE_TIMEOUT_MS = 120

#: Como terminou uma tentativa de pegar o quadro do desktop. Separar o
#: resultado da política deixa a política testável sem GPU nenhuma.
NEW_FRAME = "novo"
NO_CHANGE = "sem-mudanca"
ACCESS_LOST = "perdido"
FAILED = "falhou"


class DuplicationUnavailable(RuntimeError):
    """Esta máquina não tem como duplicar o desktop.

    Levantada só na montagem do dispositivo — máquina virtual sem GPU,
    driver antigo, sessão remota. Quem chama troca para o GDI. Falhas
    *depois* da montagem são transitórias e viram `None`, não exceção.
    """


# --- as partes puras, que os testes alcançam sem GPU -------------------


def pick_output(bounds: Sequence[Rect], rect: Rect) -> int | None:
    """Índice do monitor que contém `rect`, ou o de maior sobreposição.

    O usuário joga em ultrawide e pode ter um segundo monitor: duplicar
    o output errado devolveria a área de trabalho em vez do jogo, e o
    quadro pareceria "capturado com sucesso" enquanto o minimapa nunca
    aparece. Preferimos a contenção total e só caímos na sobreposição
    máxima quando a janela está a cavalo entre dois monitores.
    """
    melhor: int | None = None
    melhor_area = 0
    for indice, limite in enumerate(bounds):
        largura = min(limite.right, rect.right) - max(limite.x, rect.x)
        altura = min(limite.bottom, rect.bottom) - max(limite.y, rect.y)
        if largura <= 0 or altura <= 0:
            continue
        area = largura * altura
        if area == rect.width * rect.height:
            return indice
        if area > melhor_area:
            melhor, melhor_area = indice, area
    return melhor


def crop(frame: "np.ndarray", origin: Rect, rect: Rect) -> "np.ndarray | None":
    """Recorta `rect` (coordenadas de tela) do quadro do monitor `origin`.

    Converte BGRA em RGB no caminho. A ordem importa: os retratos dos
    campeões são PNGs decodificados em RGB, e o casamento de molde do
    `detect` correlaciona canal a canal — servir BGR trocaria vermelho
    com azul e derrubaria o escore de campeões de cor forte. É o mesmo
    `[:, :, 2::-1]` que o caminho GDI já faz, e é o que torna as duas
    estratégias intercambiáveis.

    Devolve `None` quando o recorte não cabe inteiro no monitor: meio
    recorte é pior que nenhum, porque o resto viraria preto e o
    detector procuraria numa imagem que não existe.
    """
    if frame is None or rect.width <= 0 or rect.height <= 0:
        return None
    x = rect.x - origin.x
    y = rect.y - origin.y
    if x < 0 or y < 0:
        return None
    if y + rect.height > frame.shape[0] or x + rect.width > frame.shape[1]:
        return None
    região = frame[y : y + rect.height, x : x + rect.width]
    if região.shape[2] < 3:
        return None
    # A cópia é obrigatória: `frame` é reaproveitado no próximo quadro e
    # uma view viraria dado corrompido na mão de quem guardou.
    return região[:, :, 2::-1].copy()


# --- COM na unha -------------------------------------------------------


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _Guid:
    """GUID a partir da forma canônica, sem depender de `ole32`."""
    limpo = text.strip("{}").replace("-", "")
    bruto = bytes.fromhex(limpo)
    valor = _Guid()
    valor.Data1 = int.from_bytes(bruto[0:4], "big")
    valor.Data2 = int.from_bytes(bruto[4:6], "big")
    valor.Data3 = int.from_bytes(bruto[6:8], "big")
    valor.Data4 = (ctypes.c_ubyte * 8)(*bruto[8:16])
    return valor


IID_DXGI_DEVICE = _guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_DXGI_OUTPUT1 = _guid("00cddea8-939b-4b83-a340-a685226666cc")
IID_D3D11_TEXTURE2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _OutputDesc(ctypes.Structure):
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("DesktopCoordinates", _Rect),
        ("AttachedToDesktop", ctypes.c_int),
        ("Rotation", ctypes.c_uint),
        ("Monitor", ctypes.c_void_p),
    ]


class _PointerPosition(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
        ("Visible", ctypes.c_int),
    ]


class _FrameInfo(ctypes.Structure):
    _fields_ = [
        ("LastPresentTime", ctypes.c_longlong),
        ("LastMouseUpdateTime", ctypes.c_longlong),
        ("AccumulatedFrames", ctypes.c_uint),
        ("RectsCoalesced", ctypes.c_int),
        ("ProtectedContentMaskedOut", ctypes.c_int),
        ("PointerPosition", _PointerPosition),
        ("TotalMetadataBufferSize", ctypes.c_uint),
        ("PointerShapeBufferSize", ctypes.c_uint),
    ]


class _SampleDesc(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_uint), ("Quality", ctypes.c_uint)]


class _Texture2DDesc(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("MipLevels", ctypes.c_uint),
        ("ArraySize", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("SampleDesc", _SampleDesc),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
    ]


class _Mapped(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", ctypes.c_uint),
        ("DepthPitch", ctypes.c_uint),
    ]


class _Com:
    """Um ponteiro de interface COM chamado por índice de vtable.

    Sem `comtypes` não existe nome de método: o que existe é a posição
    na tabela virtual, que é parte do contrato binário da interface e
    portanto tão estável quanto o nome. Os índices estão anotados um a
    um onde são usados, porque errar um deles não dá erro de compilação
    — dá corrupção de memória.
    """

    __slots__ = ("ptr",)

    def __init__(self, ptr: ctypes.c_void_p) -> None:
        self.ptr = ptr

    def __bool__(self) -> bool:
        return bool(self.ptr)

    def _method(self, index: int, restype, argtypes):
        tabela = ctypes.cast(
            self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        assinatura = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return assinatura(tabela[index])

    def call(self, index: int, argtypes, *args) -> int:
        """Chama um método que devolve HRESULT, já sem sinal."""
        return self._method(index, ctypes.c_int32, argtypes)(self.ptr, *args) & 0xFFFFFFFF

    def call_void(self, index: int, argtypes, *args) -> None:
        self._method(index, None, argtypes)(self.ptr, *args)

    def query(self, iid: _Guid) -> "_Com | None":
        saida = ctypes.c_void_p()
        # 0 = IUnknown::QueryInterface
        if self.call(0, (ctypes.c_void_p, ctypes.c_void_p), ctypes.byref(iid), ctypes.byref(saida)):
            return None
        return _Com(saida) if saida else None

    def release(self) -> None:
        if self.ptr:
            # 2 = IUnknown::Release
            try:
                self.call_void(2, ())
            except Exception:  # pragma: no cover - rede de segurança
                pass
            self.ptr = None


def _release(*objetos) -> None:
    for objeto in objetos:
        if isinstance(objeto, _Com):
            objeto.release()


# --- o grabber ---------------------------------------------------------


class DuplicationGrabber:
    """Captura de tela via Desktop Duplication, com a API do GDI.

    Um objeto por thread, como o `ScreenGrabber`: o dispositivo D3D e a
    textura de staging são estado mutável compartilhado e não há trava
    aqui de propósito. É usado só na thread `lolqueue-selva`.
    """

    def __init__(self) -> None:
        self._device: _Com | None = None
        self._context: _Com | None = None
        self._adapter: _Com | None = None
        self._duplication: _Com | None = None
        self._staging: _Com | None = None
        self._staging_size: tuple[int, int] | None = None
        self._output_index: int | None = None
        self._origin: Rect | None = None
        self._last: "np.ndarray | None" = None
        self._pending_first = False
        self._closed = False

    # -- montagem -------------------------------------------------------

    def prepare(self) -> None:
        """Monta o dispositivo agora, para a falha aparecer agora.

        Existe para o `capture` poder decidir cedo entre DXGI e GDI: se
        a máquina não duplica o desktop, isto levanta
        `DuplicationUnavailable` na primeira captura em vez de devolver
        `None` em silêncio por vários segundos.
        """
        self._ensure_device()

    def _ensure_device(self) -> None:
        """Cria o dispositivo D3D11 e guarda o adaptador que o serve.

        Levanta `DuplicationUnavailable` porque *esta* é a falha que o
        `capture` usa para decidir cair no GDI de vez.
        """
        if self._device is not None:
            return
        try:
            d3d11 = ctypes.windll.d3d11
        except Exception as erro:  # pragma: no cover - sem d3d11.dll
            raise DuplicationUnavailable("d3d11.dll indisponível") from erro

        device = ctypes.c_void_p()
        context = ctypes.c_void_p()
        nivel = ctypes.c_uint(0)
        d3d11.D3D11CreateDevice.restype = ctypes.c_int32
        resultado = (
            d3d11.D3D11CreateDevice(
                None,
                D3D_DRIVER_TYPE_HARDWARE,
                None,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                None,
                0,
                D3D11_SDK_VERSION,
                ctypes.byref(device),
                ctypes.byref(nivel),
                ctypes.byref(context),
            )
            & 0xFFFFFFFF
        )
        if resultado or not device.value:
            raise DuplicationUnavailable(f"D3D11CreateDevice falhou (0x{resultado:08X})")

        dispositivo = _Com(device)
        contexto = _Com(context)
        dxgi = dispositivo.query(IID_DXGI_DEVICE)
        if dxgi is None:
            _release(dispositivo, contexto)
            raise DuplicationUnavailable("dispositivo sem IDXGIDevice")
        adaptador = ctypes.c_void_p()
        # 7 = IDXGIDevice::GetAdapter (0-2 IUnknown, 3-6 IDXGIObject)
        falhou = dxgi.call(7, (ctypes.c_void_p,), ctypes.byref(adaptador))
        _release(dxgi)
        if falhou or not adaptador.value:
            _release(dispositivo, contexto)
            raise DuplicationUnavailable("adaptador DXGI indisponível")

        self._device = dispositivo
        self._context = contexto
        self._adapter = _Com(adaptador)

    def _outputs(self) -> list[tuple[int, Rect]]:
        """Os monitores deste adaptador, com o retângulo de cada um."""
        limites: list[tuple[int, Rect]] = []
        indice = 0
        while True:
            saida = ctypes.c_void_p()
            # 7 = IDXGIAdapter::EnumOutputs
            resultado = self._adapter.call(
                7, (ctypes.c_uint, ctypes.c_void_p), indice, ctypes.byref(saida)
            )
            if resultado == DXGI_ERROR_NOT_FOUND or not saida.value:
                break
            monitor = _Com(saida)
            desc = _OutputDesc()
            # 7 = IDXGIOutput::GetDesc
            if not monitor.call(7, (ctypes.c_void_p,), ctypes.byref(desc)):
                caixa = desc.DesktopCoordinates
                limites.append(
                    (
                        indice,
                        Rect(
                            int(caixa.left),
                            int(caixa.top),
                            int(caixa.right - caixa.left),
                            int(caixa.bottom - caixa.top),
                        ),
                    )
                )
            _release(monitor)
            indice += 1
            if indice > 16:  # pragma: no cover - paranoia contra laço infinito
                break
        return limites

    def _ensure_duplication(self, rect: Rect) -> None:
        """Garante uma duplicação ativa do monitor que contém `rect`."""
        self._ensure_device()
        if self._duplication is not None and self._origin is not None:
            dentro = (
                self._origin.x <= rect.x
                and self._origin.y <= rect.y
                and rect.right <= self._origin.right
                and rect.bottom <= self._origin.bottom
            )
            if dentro:
                return
            # O jogo mudou de monitor (ou passou a cavalar dois): a
            # duplicação antiga não cobre mais o retângulo pedido, e
            # insistir nela devolveria recorte cortado ou nenhum.
            self._drop_duplication()

        limites = self._outputs()
        if not limites:
            raise DuplicationUnavailable("nenhum monitor exposto pelo adaptador")
        escolhido = pick_output([limite for _, limite in limites], rect)
        if escolhido is None:
            raise OSError("o retângulo pedido não cai em nenhum monitor")
        indice, origem = limites[escolhido]

        saida = ctypes.c_void_p()
        if self._adapter.call(
            7, (ctypes.c_uint, ctypes.c_void_p), indice, ctypes.byref(saida)
        ) or not saida.value:
            raise OSError("não foi possível reabrir o monitor escolhido")
        monitor = _Com(saida)
        moderno = monitor.query(IID_DXGI_OUTPUT1)
        _release(monitor)
        if moderno is None:
            raise DuplicationUnavailable("monitor sem IDXGIOutput1")

        duplicacao = ctypes.c_void_p()
        # 22 = IDXGIOutput1::DuplicateOutput
        resultado = moderno.call(
            22, (ctypes.c_void_p, ctypes.c_void_p), self._device.ptr, ctypes.byref(duplicacao)
        )
        _release(moderno)
        if resultado or not duplicacao.value:
            # Falha aqui é transitória com frequência (troca de modo de
            # vídeo em curso, outra aplicação duplicando o mesmo
            # monitor), então é OSError e não `DuplicationUnavailable`:
            # não queremos degradar para GDI para sempre por causa de
            # um instante ruim.
            raise OSError(f"DuplicateOutput falhou (0x{resultado:08X})")

        self._duplication = _Com(duplicacao)
        self._output_index = indice
        self._origin = origem
        self._last = None
        self._pending_first = True

    def _ensure_staging(self, width: int, height: int) -> None:
        """Textura legível pela CPU, do tamanho do monitor.

        A textura que a duplicação entrega vive só na GPU; `Map` só
        funciona em recurso `STAGING` com acesso de leitura. É por isso
        que existe uma cópia intermediária, e não por descuido.
        """
        if self._staging is not None and self._staging_size == (width, height):
            return
        _release(self._staging)
        self._staging = None
        self._staging_size = None

        desc = _Texture2DDesc(
            Width=width,
            Height=height,
            MipLevels=1,
            ArraySize=1,
            Format=DXGI_FORMAT_B8G8R8A8_UNORM,
            SampleDesc=_SampleDesc(1, 0),
            Usage=D3D11_USAGE_STAGING,
            BindFlags=0,
            CPUAccessFlags=D3D11_CPU_ACCESS_READ,
            MiscFlags=0,
        )
        textura = ctypes.c_void_p()
        # 5 = ID3D11Device::CreateTexture2D
        if self._device.call(
            5,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            ctypes.byref(desc),
            None,
            ctypes.byref(textura),
        ) or not textura.value:
            raise OSError("não foi possível alocar a textura de leitura")
        self._staging = _Com(textura)
        self._staging_size = (width, height)

    # -- captura --------------------------------------------------------

    def _pull(self, rect: Rect) -> tuple[str, "np.ndarray | None"]:
        """Um quadro novo do monitor inteiro, em BGRA, ou o motivo de não.

        Este é o único ponto que fala com a GPU; a política de cache
        fica no `grab`, que os testes exercitam trocando este método.
        """
        import numpy as np

        self._ensure_duplication(rect)

        info = _FrameInfo()
        recurso = ctypes.c_void_p()
        # 8 = IDXGIOutputDuplication::AcquireNextFrame
        resultado = self._duplication.call(
            8,
            (ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p),
            ACQUIRE_TIMEOUT_MS,
            ctypes.byref(info),
            ctypes.byref(recurso),
        )
        if resultado == DXGI_ERROR_WAIT_TIMEOUT:
            return NO_CHANGE, None
        if resultado == DXGI_ERROR_ACCESS_LOST:
            return ACCESS_LOST, None
        if resultado or not recurso.value:
            return FAILED, None

        quadro = _Com(recurso)
        textura = None
        try:
            textura = quadro.query(IID_D3D11_TEXTURE2D)
            if textura is None:
                return FAILED, None
            desc = _Texture2DDesc()
            # 10 = ID3D11Texture2D::GetDesc (0-2 IUnknown, 3-6
            # ID3D11DeviceChild, 7-9 ID3D11Resource)
            textura.call_void(10, (ctypes.c_void_p,), ctypes.byref(desc))
            largura, altura = int(desc.Width), int(desc.Height)
            if largura <= 0 or altura <= 0:
                return FAILED, None
            self._ensure_staging(largura, altura)
            # 47 = ID3D11DeviceContext::CopyResource
            self._context.call_void(
                47, (ctypes.c_void_p, ctypes.c_void_p), self._staging.ptr, textura.ptr
            )
            mapeado = _Mapped()
            # 14 = ID3D11DeviceContext::Map
            if self._context.call(
                14,
                (ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p),
                self._staging.ptr,
                0,
                D3D11_MAP_READ,
                0,
                ctypes.byref(mapeado),
            ) or not mapeado.pData:
                return FAILED, None
            try:
                passo = int(mapeado.RowPitch)
                bruto = (ctypes.c_ubyte * (passo * altura)).from_address(mapeado.pData)
                # A linha pode ser mais larga que a imagem (alinhamento
                # da GPU): reconstruir por `RowPitch` e só então cortar.
                linhas = np.frombuffer(bruto, dtype=np.uint8).reshape(altura, passo)
                imagem = linhas[:, : largura * 4].reshape(altura, largura, 4)
                # Cópia contígua e barata (memcpy por linha); a troca de
                # canais fica para o recorte, que é pequeno.
                pronto = imagem.copy()
            finally:
                # 15 = ID3D11DeviceContext::Unmap
                self._context.call_void(
                    15, (ctypes.c_void_p, ctypes.c_uint), self._staging.ptr, 0
                )
            return NEW_FRAME, pronto
        finally:
            _release(textura, quadro)
            # 14 = IDXGIOutputDuplication::ReleaseFrame. Fora do `if`
            # de sucesso de propósito: segurar o quadro trava todas as
            # aquisições seguintes.
            try:
                self._duplication.call_void(14, ())
            except Exception:  # pragma: no cover - rede de segurança
                pass

    def grab(self, rect: Rect) -> "np.ndarray | None":
        """Os pixels de `rect` como RGB (altura, largura, 3), ou `None`.

        Mesmo contrato do `ScreenGrabber`: falha vira `None`, porque
        falha aqui é rotina — troca de modo de vídeo, tela bloqueada,
        jogo fechando. Quem chama tenta de novo no próximo tique.
        """
        if self._closed or rect.width <= 0 or rect.height <= 0:
            return None
        try:
            estado, quadro = self._pull(rect)
        except Exception:
            return None

        if estado == NEW_FRAME and quadro is not None:
            if self._pending_first:
                self._pending_first = False
                # Observado ao vivo: a primeira aquisição depois de
                # `DuplicateOutput` costuma vir com a textura zerada — o
                # DXGI ainda não tem um quadro apresentado para entregar.
                # Guardar esse quadro faria o vigia concluir "tela
                # ilegível" logo no começo da partida, que é justamente o
                # diagnóstico errado que este módulo veio consertar.
                if not quadro.any():
                    return None
            self._last = quadro
        elif estado == ACCESS_LOST:
            # A duplicação morreu; o cache virou passado e o próximo
            # `grab` monta tudo de novo. Um quadro perdido é barato.
            self._drop_duplication()
            return None
        elif estado == FAILED:
            return None
        # NO_CHANGE cai aqui de propósito: a tela não mudou, então o
        # último quadro continua sendo a verdade.

        if self._last is None or self._origin is None:
            return None
        try:
            return crop(self._last, self._origin, rect)
        except Exception:  # pragma: no cover - rede de segurança
            return None

    # -- ciclo de vida --------------------------------------------------

    def _drop_duplication(self) -> None:
        _release(self._duplication)
        self._duplication = None
        self._origin = None
        self._output_index = None
        self._last = None
        self._pending_first = False

    def close(self) -> None:
        self._closed = True
        self._drop_duplication()
        _release(self._staging, self._adapter, self._context, self._device)
        self._staging = None
        self._staging_size = None
        self._adapter = self._context = self._device = None

    def __enter__(self) -> "DuplicationGrabber":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - rede de segurança
        try:
            self.close()
        except Exception:
            pass
