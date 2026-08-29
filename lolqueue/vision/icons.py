"""O retrato do campeão virando molde para procurar no minimapa.

O que o Data Dragon entrega é um quadrado de 120 px pensado para a
interface. O que aparece no minimapa é outra coisa: o mesmo desenho
recortado num círculo, com um anel da cor do time em volta, e reduzido
a algo em torno de vinte pixels. Este módulo faz essa travessia — busca,
guarda em disco e prepara — para que `detect` receba um molde pronto e
não precise saber de onde ele veio.

Duas decisões que parecem detalhe e não são:

**O PNG é decodificado à mão.** O app se distribui como executável
único e as dependências declaradas são numpy e requests; puxar um
decodificador de imagem inteiro para ler 170 quadradinhos seria pagar
caro por pouco. `zlib` já vem no Python e o resto do PNG são cinco
filtros de linha.

**O anel do time fica fora da conta.** Ele é a única parte do ícone que
muda conforme o campeão esteja no seu time ou no inimigo. Casar o molde
incluindo o anel faria o retrato do inimigo — exatamente o que
procuramos — ser o que casa pior.

A rede é injetável porque nenhum teste pode depender do Data Dragon
estar de pé.
"""

from __future__ import annotations

import json
import os
import re
import struct
import time
import zlib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Callable

import numpy as np

DDRAGON = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON}/api/versions.json"
CATALOG_URL = DDRAGON + "/cdn/{version}/data/en_US/champion.json"
ICON_URL = DDRAGON + "/cdn/{version}/img/champion/{key}.png"

#: Até onde o molde vai, em fração do raio. O que sobra de fora é o
#: anel do time mais o canto quadrado que o minimapa nem desenha.
RING_FRACTION = 0.78

#: Assinatura de um PNG. Um cache truncado começa a valer nada aqui.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Quantos canais tem cada tipo de cor do PNG. Os que faltam —
#: paletados e 16 bits — não aparecem no Data Dragon, e recusar é
#: melhor que decodificar errado.
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}

_NOT_ALNUM = re.compile(r"[^0-9a-z]+")


def cache_dir() -> Path:
    """Onde os retratos ficam, ao lado do resto do que o app guarda."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "icones"


def normalize_name(name: str) -> str:
    """Nome de campeão reduzido ao que dá para comparar.

    "Kai'Sa", "KaiSa" e "kai sa" têm que cair no mesmo lugar: o nome que
    a partida informa e o que o Data Dragon usa quase nunca são iguais
    caractere a caractere.
    """
    return _NOT_ALNUM.sub("", name.casefold())


def guess_key(name: str) -> str:
    """Palpite do nome de arquivo a partir do nome de tela.

    Vale só enquanto o catálogo não responde. Acerta a maioria — tirar
    espaços e apóstrofos de "Lee Sin" dá "LeeSin" — e erra os poucos em
    que o arquivo não deriva do nome, como Wukong, que no Data Dragon é
    MonkeyKing.
    """
    return re.sub(r"[^0-9A-Za-z]+", "", name)


# --- PNG ---------------------------------------------------------------


def _chunks(data: bytes):
    """Percorre os pedaços do PNG. Para no primeiro que não fecha."""
    offset = len(PNG_MAGIC)
    total = len(data)
    while offset + 8 <= total:
        (length,) = struct.unpack_from(">I", data, offset)
        kind = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > total:
            return
        yield kind, data[start:end]
        offset = end + 4


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> np.ndarray | None:
    """Desfaz os filtros de linha, que é o miolo do formato.

    Cada linha do PNG é gravada como diferença para os vizinhos de cima
    e da esquerda — e a de cima já desfiltrada, o que obriga a percorrer
    linha a linha em ordem. Só o filtro "Up" é vetorizável; os outros
    dependem do pixel imediatamente anterior da mesma linha e precisam
    do laço. Custa uns milissegundos por retrato, uma vez na vida de
    cada campeão, contra um decodificador inteiro no executável.
    """
    saida = np.zeros((height, stride), np.uint8)
    anterior = np.zeros(stride, np.int32)
    for y in range(height):
        base = y * (stride + 1)
        tipo = raw[base]
        linha = np.frombuffer(raw, np.uint8, count=stride, offset=base + 1)
        atual = linha.astype(np.int32)
        if tipo == 0:
            pass
        elif tipo == 1:
            for i in range(bpp, stride):
                atual[i] = (atual[i] + atual[i - bpp]) & 0xFF
        elif tipo == 2:
            atual = (atual + anterior) & 0xFF
        elif tipo == 3:
            for i in range(stride):
                esquerda = atual[i - bpp] if i >= bpp else 0
                atual[i] = (atual[i] + ((esquerda + anterior[i]) >> 1)) & 0xFF
        elif tipo == 4:
            for i in range(stride):
                a = int(atual[i - bpp]) if i >= bpp else 0
                b = int(anterior[i])
                c = int(anterior[i - bpp]) if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                atual[i] = (atual[i] + pred) & 0xFF
        else:
            return None
        saida[y] = atual.astype(np.uint8)
        anterior = atual
    return saida


def decode_png(data: bytes | None) -> np.ndarray | None:
    """Um PNG de 8 bits como RGB (altura, largura, 3), ou `None`.

    Devolve `None` para qualquer coisa que não dê para ler, inclusive
    arquivo pela metade: cache corrompido é rotina — um download
    interrompido, um disco cheio — e não pode virar exceção dentro do
    laço que avisa o jogador.
    """
    if not data or not data.startswith(PNG_MAGIC):
        return None

    cabecalho = None
    comprimido = bytearray()
    for kind, payload in _chunks(data):
        if kind == b"IHDR" and len(payload) >= 13:
            cabecalho = struct.unpack(">IIBBBBB", payload[:13])
        elif kind == b"IDAT":
            comprimido += payload
        elif kind == b"IEND":
            break
    if cabecalho is None or not comprimido:
        return None

    largura, altura, profundidade, cor, _comp, _filtro, entrelacado = cabecalho
    canais = PNG_CHANNELS.get(cor)
    if canais is None or profundidade != 8 or entrelacado != 0:
        return None
    if largura <= 0 or altura <= 0:
        return None

    try:
        raw = zlib.decompress(bytes(comprimido))
    except zlib.error:
        return None

    stride = largura * canais
    if len(raw) < (stride + 1) * altura:
        return None

    plano = _unfilter(raw, altura, stride, canais)
    if plano is None:
        return None

    pixels = plano.reshape(altura, largura, canais)
    if canais == 1:
        return np.repeat(pixels, 3, axis=2)
    if canais == 2:
        return np.repeat(pixels[:, :, :1], 3, axis=2)
    return pixels[:, :, :3].copy()


# --- preparo do molde --------------------------------------------------


def _axis_weights(source: int, target: int) -> np.ndarray:
    """Peso de cada pixel de origem em cada pixel de destino.

    Redução por média de área, e não por amostragem: o retrato vem com
    120 px e no minimapa cabe em vinte e poucos. Pegar um pixel a cada
    cinco jogaria fora cinco sextos do desenho e o molde viraria ruído.
    """
    bordas = np.linspace(0.0, source, target + 1)
    indices = np.arange(source, dtype=np.float64)
    inicio = np.maximum(bordas[:-1, None], indices[None, :])
    fim = np.minimum(bordas[1:, None], indices[None, :] + 1.0)
    pesos = np.clip(fim - inicio, 0.0, None)
    return pesos / pesos.sum(axis=1, keepdims=True)


def resize(image: np.ndarray, size: int) -> np.ndarray:
    """O retrato quadrado reduzido a `size` pixels de lado, em float."""
    dados = image.astype(np.float64)
    if dados.shape[0] == size and dados.shape[1] == size:
        return dados
    linhas = _axis_weights(dados.shape[0], size)
    colunas = _axis_weights(dados.shape[1], size)
    return np.einsum("yi,xj,ijc->yxc", linhas, colunas, dados)


def circular_mask(size: int, radius: float = RING_FRACTION) -> np.ndarray:
    """Quais pixels do molde entram na conta.

    O disco de dentro, sem o anel do time e sem os cantos do quadrado —
    que no minimapa nem existem, já que o ícone é redondo.
    """
    meio = (size - 1) / 2.0
    eixo = (np.arange(size) - meio) / max(meio, 1e-9)
    distancia = np.hypot(eixo[:, None], eixo[None, :])
    return distancia <= radius


@dataclass(frozen=True)
class Template:
    """Um molde pronto para a correlação.

    Guarda também o que a correlação precisaria recalcular a cada
    quadro — média e energia dentro da máscara —, porque o molde vive
    muito mais que um quadro e a conta é sempre a mesma.
    """

    pixels: np.ndarray
    mask: np.ndarray

    @classmethod
    def from_portrait(cls, portrait: np.ndarray, size: int) -> "Template":
        return cls(resize(portrait, size), circular_mask(size))

    @property
    def size(self) -> int:
        return int(self.pixels.shape[0])

    @cached_property
    def count(self) -> int:
        """Quantos valores entram na conta, contando os três canais."""
        return int(self.mask.sum()) * int(self.pixels.shape[2])

    @cached_property
    def centered(self) -> np.ndarray:
        """O molde sem a média, e zerado fora da máscara.

        Zerar fora é o que permite somar o quadro inteiro sem separar o
        que está dentro do disco: o de fora multiplica por zero.
        """
        recorte = self.mask[:, :, None]
        media = float((self.pixels * recorte).sum() / max(self.count, 1))
        return (self.pixels - media) * recorte

    @cached_property
    def energy(self) -> float:
        """Raiz da soma dos quadrados — o denominador do lado do molde."""
        return float(np.sqrt((self.centered**2).sum()))


# --- busca e cache -----------------------------------------------------


def _http_get(url: str, timeout: float = 6.0) -> bytes | None:
    """Um GET que nunca estoura. Falha vira `None` e o app segue mudo."""
    try:
        import requests

        resposta = requests.get(url, timeout=timeout)
    except Exception:
        return None
    if resposta.status_code >= 400:
        return None
    return resposta.content


Fetcher = Callable[[str], "bytes | None"]

#: Quanto esperar antes de tentar baixar de novo um retrato que falhou.
#: Existe por causa de uma troca ruim: guardar o fracasso para sempre
#: apagava o campeão da partida inteira depois de um único soluço de
#: rede, e não guardar nada faria o laço de captura pedir o mesmo
#: arquivo cinco vezes por segundo — com seis segundos de espera cada.
RETRY_SECONDS = 30.0


class ChampionIcons:
    """Retratos do Data Dragon, em cache no disco e prontos para casar.

    Nenhum método estoura: sem rede, sem catálogo ou com o cache
    corrompido, o resultado é `None` e o aviso simplesmente não sai
    naquele quadro.
    """

    def __init__(
        self,
        directory: Path | None = None,
        fetch: Fetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dir = Path(directory) if directory is not None else cache_dir()
        self._fetch = fetch or _http_get
        self._clock = clock
        self._version: str | None = None
        self._version_falhou: float | None = None
        self._keys: dict[str, str] | None = None
        self._keys_falhou: float | None = None
        self._portraits: dict[str, np.ndarray] = {}
        self._falhas: dict[str, float] = {}
        self._templates: dict[tuple[str, int], Template] = {}

    @property
    def directory(self) -> Path:
        return self._dir

    # -- rede e disco ---------------------------------------------------

    def _get(self, url: str) -> bytes | None:
        try:
            return self._fetch(url)
        except Exception:
            # Rede injetada por quem chama; uma exceção dela não pode
            # subir para dentro do laço de captura.
            return None

    def _read_cache(self, name: str) -> bytes | None:
        try:
            return (self._dir / name).read_bytes()
        except OSError:
            return None

    def _write_cache(self, name: str, data: bytes) -> None:
        """Grava por temporário: download interrompido não vira cache."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            alvo = self._dir / name
            temp = alvo.with_name(alvo.name + ".part")
            temp.write_bytes(data)
            temp.replace(alvo)
        except OSError:
            pass

    def version(self) -> str | None:
        """A versão mais recente do Data Dragon.

        Guardada em disco para que uma abertura sem internet ainda saiba
        de qual pasta os retratos vieram — o ícone em cache continua
        servindo, e um patch de diferença não muda o desenho.
        """
        if self._version is not None:
            return self._version
        if self._espera(self._version_falhou):
            return None
        bruto = self._get(VERSIONS_URL)
        if bruto:
            try:
                versoes = json.loads(bruto)
            except ValueError:
                versoes = None
            if isinstance(versoes, list) and versoes:
                self._version = str(versoes[0])
                self._write_cache("versao.txt", self._version.encode())
                return self._version
        guardada = self._read_cache("versao.txt")
        if guardada:
            self._version = guardada.decode("utf-8", "ignore").strip() or None
        if self._version is None:
            # Sem isto, um PC sem internet pediria esta lista a cada
            # quadro — e cada pedido gasta o tempo inteiro do timeout
            # parado dentro do laço de captura.
            self._version_falhou = self._clock()
        return self._version

    def _espera(self, desde: float | None) -> bool:
        """Se ainda é cedo demais para tentar de novo o que falhou."""
        return desde is not None and self._clock() - desde < RETRY_SECONDS

    def _catalog(self) -> dict[str, str]:
        """Nome de tela normalizado para nome de arquivo do Data Dragon.

        Um catálogo vazio é falta de resposta, não resposta: guardá-lo
        deixava o app o resto da sessão adivinhando nome de arquivo, e o
        palpite erra justamente nos campeões cujo nome de tela não é o
        nome do arquivo — Wukong, Nunu, Renata. Fica valendo por
        `RETRY_SECONDS`, como os retratos.
        """
        if self._keys:
            return self._keys
        if self._espera(self._keys_falhou):
            return self._keys or {}

        versao = self.version()
        guardado = self._read_cache("campeoes.json")
        if guardado:
            try:
                dados = json.loads(guardado)
            except ValueError:
                dados = None
            if isinstance(dados, dict) and dados.get("versao") == versao:
                chaves = dados.get("chaves")
                if isinstance(chaves, dict):
                    self._keys = {str(k): str(v) for k, v in chaves.items()}
                    return self._keys

        self._keys = {}
        if versao:
            bruto = self._get(CATALOG_URL.format(version=versao))
            if bruto:
                try:
                    dados = json.loads(bruto)
                except ValueError:
                    dados = None
                entradas = (dados or {}).get("data")
                if isinstance(entradas, dict):
                    for chave, entrada in entradas.items():
                        nome = (entrada or {}).get("name") or chave
                        self._keys[normalize_name(str(nome))] = str(chave)
                    if self._keys:
                        self._write_cache(
                            "campeoes.json",
                            json.dumps(
                                {"versao": versao, "chaves": self._keys},
                                ensure_ascii=False,
                            ).encode("utf-8"),
                        )
        if not self._keys:
            self._keys_falhou = self._clock()
        return self._keys

    # -- o que interessa ------------------------------------------------

    def key_for(self, champion: str) -> str | None:
        """Nome de arquivo do campeão, ou `None` se nem o palpite serve."""
        if not champion:
            return None
        chave = self._catalog().get(normalize_name(champion))
        return chave or (guess_key(champion) or None)

    def portrait(self, champion: str) -> np.ndarray | None:
        """O retrato de 120 px, do disco ou da rede.

        Falha não vira resposta definitiva. A primeira partida numa
        máquina nova roda com o cache vazio, e um soluço de rede na hora
        errada — o app abre bem antes do jogo começar — apagava aquele
        campeão do resto da sessão: o molde nunca era montado, o inimigo
        nunca casava e o aviso dele simplesmente não saía, sem uma linha
        dizendo o motivo. Agora o fracasso vale `RETRY_SECONDS` e a
        internet voltando conserta sozinha.
        """
        chave = self.key_for(champion)
        if chave is None:
            return None
        pronto = self._portraits.get(chave)
        if pronto is not None:
            return pronto
        desde = self._falhas.get(chave)
        if desde is not None and self._clock() - desde < RETRY_SECONDS:
            return None

        arquivo = f"{chave}.png"
        imagem = decode_png(self._read_cache(arquivo))
        if imagem is None:
            versao = self.version()
            if versao:
                bruto = self._get(ICON_URL.format(version=versao, key=chave))
                imagem = decode_png(bruto)
                if imagem is not None and bruto:
                    # Só grava o que soube ler: um PNG que o próprio
                    # decodificador recusa voltaria a ser recusado toda
                    # abertura, e o cache serviria para nada.
                    self._write_cache(arquivo, bruto)
        if imagem is None:
            self._falhas[chave] = self._clock()
            return None
        self._portraits[chave] = imagem
        self._falhas.pop(chave, None)
        return imagem

    def template(self, champion: str, size: int) -> Template | None:
        """O molde do campeão no tamanho que ele tem naquele minimapa."""
        if size < 4:
            return None
        chave = self.key_for(champion)
        if chave is None:
            return None
        pedido = (chave, int(size))
        pronto = self._templates.get(pedido)
        if pronto is not None:
            return pronto
        imagem = self.portrait(champion)
        if imagem is None:
            return None
        molde = Template.from_portrait(imagem, int(size))
        self._templates[pedido] = molde
        return molde
