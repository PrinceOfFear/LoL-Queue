"""Procurar o retrato do jungler dentro do recorte do minimapa.

A conta é correlação cruzada normalizada com máscara. "Normalizada"
porque o ícone no minimapa não tem o brilho do retrato original: o
nevoeiro escurece, um clarão de habilidade estoura, e o próprio jogo
desenha o ícone por cima do terreno. Comparar por diferença de pixel
quebraria em todos esses casos; comparar por correlação sobrevive a
qualquer mudança de brilho e contraste, porque subtrai a média e divide
pelo desvio dos dois lados.

"Com máscara" porque o anel do time fica de fora — ver `icons`.

Duas decisões de implementação que valem explicação:

**FFT em vez do laço direto.** Um minimapa de 260 px com um molde de 20
dá 58 mil posições, cada uma somando 1200 valores: 70 milhões de
multiplicações por molde, por quadro, e são três moldes e cinco quadros
por segundo. Pela transformada a mesma conta cai para alguns
milissegundos, porque correlação no espaço é produto na frequência.

**Os espectros do molde ficam guardados.** O molde não muda durante a
partida; o quadro muda. Transformar o molde uma vez por tamanho de
recorte tira um terço do trabalho de cada quadro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .icons import Template

#: Abaixo disto não se fala. Correlação mascarada de um ícone contra ele
#: mesmo fica perto de 1; terreno sem o ícone raramente passa de 0,3. O
#: limiar alto é de propósito: falar o nome errado custa mais caro que
#: não falar nada.
THRESHOLD = 0.85

#: Quantos quadros seguidos precisam concordar antes do aviso sair. Um
#: casamento solto pode ser um brilho passageiro; três em sequência, no
#: mesmo lugar, não.
CONFIRM_FRAMES = 3

#: O quanto o ícone pode ter andado entre dois quadros e ainda ser o
#: mesmo ícone, em frações do próprio lado. Dois casamentos em pontas
#: opostas do mapa são dois eventos, e contá-los juntos deixaria um
#: falso positivo virar aviso.
JUMP_FRACTION = 1.0

#: Quantos quadros vazios seguidos um casamento já confirmado sobrevive.
#: O ícone do inimigo pisca o tempo todo — o nevoeiro cobre por um
#: instante, um clarão estoura por cima, outro ícone passa na frente — e
#: esquecer tudo no primeiro quadro vazio cobrava três quadros novos,
#: mais de meio segundo, para voltar a falar de alguém que nunca saiu do
#: lugar. Num aviso de gank, meio segundo é a diferença entre recuar e
#: morrer. Antes da confirmação nada é perdoado: é lá que mora a defesa
#: contra o falso positivo, e ela fica exatamente como era.
FORGIVE_FRAMES = 2

_EPS = 1e-9


@dataclass(frozen=True)
class Match:
    """Onde o ícone apareceu, em pixels do recorte examinado.

    `x` e `y` são o centro do ícone, e não o canto, porque é o centro
    que vira posição no mapa.
    """

    x: int
    y: int
    score: float
    size: int


@dataclass(frozen=True)
class _Kernels:
    """O molde já transformado, para um tamanho de recorte específico."""

    mask: np.ndarray
    layers: tuple[np.ndarray, ...]


def _as_frame(frame: np.ndarray | None) -> np.ndarray | None:
    """O quadro em float, ou `None` se não der para usar.

    A captura falha com frequência — janela minimizada, troca de
    resolução, tela de carregamento — e quem chama não deveria ter que
    conferir isso a cada quadro.
    """
    if frame is None:
        return None
    dados = np.asarray(frame)
    if dados.ndim != 3 or dados.shape[2] < 3:
        return None
    return dados[:, :, :3].astype(np.float64)


def _frame_spectra(frame: np.ndarray) -> tuple[np.ndarray, ...]:
    """Transformadas do quadro: cada canal, a soma e a soma dos quadrados.

    A soma e a soma dos quadrados são o que a normalização precisa —
    média e energia da janela sob a máscara — e valem para qualquer
    molde, então saem uma vez por quadro e não uma vez por molde.
    """
    canais = tuple(np.fft.rfft2(frame[:, :, c]) for c in range(3))
    soma = canais[0] + canais[1] + canais[2]
    quadrados = np.fft.rfft2((frame**2).sum(axis=2))
    return canais + (soma, quadrados)


def _template_spectra(template: Template, shape: tuple[int, int]) -> _Kernels:
    mascara = template.mask.astype(np.float64)
    centrado = template.centered
    return _Kernels(
        mask=np.fft.rfft2(mascara, s=shape),
        layers=tuple(np.fft.rfft2(centrado[:, :, c], s=shape) for c in range(3)),
    )


def _valid(spectrum: np.ndarray, shape: tuple[int, int], size: int) -> np.ndarray:
    """A parte da correlação circular que não deu a volta na imagem.

    A transformada devolve correlação circular; as posições em que o
    molde ainda cabe inteiro dentro do quadro são exatamente as de uma
    correlação "valid", e são só essas que se aproveita.
    """
    altura, largura = shape
    inteiro = np.fft.irfft2(spectrum, s=shape)
    return inteiro[: altura - size + 1, : largura - size + 1]


def score_map(
    frame: np.ndarray | None,
    template: Template,
    spectra: tuple[np.ndarray, ...] | None = None,
    kernels: _Kernels | None = None,
) -> np.ndarray | None:
    """A correlação em cada posição possível, entre -1 e 1.

    Devolve `None` quando a conta não faz sentido: quadro que não veio,
    molde maior que o recorte, molde chapado.
    """
    dados = _as_frame(frame) if spectra is None else frame
    if dados is None:
        return None

    altura, largura = dados.shape[:2]
    lado = template.size
    if lado < 1 or lado > altura or lado > largura:
        return None
    if template.energy <= _EPS or template.count <= 0:
        return None

    forma = (altura, largura)
    if spectra is None:
        spectra = _frame_spectra(dados)
    if kernels is None:
        kernels = _template_spectra(template, forma)

    # O numerador soma os três canais; somar ainda na frequência poupa
    # duas transformadas inversas, que é a parte cara.
    misturado = kernels.layers[0] * 0
    for canal, camada in zip(spectra[:3], kernels.layers):
        misturado = misturado + canal * np.conj(camada)

    numerador = _valid(misturado, forma, lado)
    soma = _valid(spectra[3] * np.conj(kernels.mask), forma, lado)
    quadrados = _valid(spectra[4] * np.conj(kernels.mask), forma, lado)

    n = float(template.count)
    # Energia da janela sob a máscara. O `maximum` existe porque a
    # transformada devolve zero com erro de arredondamento, e uma região
    # chapada pode sair negativa por um fio.
    energia = np.sqrt(np.maximum(quadrados - (soma**2) / n, 0.0))
    denominador = energia * template.energy
    return np.where(
        denominador > _EPS,
        numerador / np.maximum(denominador, _EPS),
        0.0,
    )


def _best(
    mapa: np.ndarray | None, template: Template, threshold: float
) -> Match | None:
    if mapa is None or mapa.size == 0:
        return None
    plano = int(np.argmax(mapa))
    y, x = divmod(plano, mapa.shape[1])
    valor = float(mapa[y, x])
    if valor < threshold:
        return None
    meio = template.size // 2
    return Match(x=int(x) + meio, y=int(y) + meio, score=valor, size=template.size)


def match_template(
    frame: np.ndarray | None,
    template: Template,
    threshold: float = THRESHOLD,
) -> Match | None:
    """A melhor posição do molde no quadro, se passar do limiar."""
    return _best(score_map(frame, template), template, threshold)


class Detector:
    """Vários moldes do mesmo campeão, com confirmação ao longo do tempo.

    Os moldes são o mesmo retrato em tamanhos diferentes: o ícone no
    minimapa cresce e encolhe com o controle de escala do jogo, e o
    tamanho certo só se descobre vendo qual casa melhor.

    A confirmação é o que separa um aviso de um susto. Só depois de
    `CONFIRM_FRAMES` quadros seguidos casando perto do mesmo ponto o
    detector devolve alguma coisa; a partir daí devolve todo quadro,
    porque acompanhar o inimigo depois do primeiro aviso não pode ter
    atraso.
    """

    def __init__(
        self,
        templates: Iterable[Template],
        threshold: float = THRESHOLD,
        confirm: int = CONFIRM_FRAMES,
        forgive: int = FORGIVE_FRAMES,
    ) -> None:
        self._templates = [t for t in templates if t.size >= 1]
        self._threshold = float(threshold)
        self._confirm = max(1, int(confirm))
        self._forgive = max(0, int(forgive))
        self._kernels: dict[tuple[int, tuple[int, int]], _Kernels] = {}
        self._last: Match | None = None
        self._streak = 0
        self._confirmed = False
        self._misses = 0

    @property
    def templates(self) -> list[Template]:
        return list(self._templates)

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    def reset(self) -> None:
        """Esquece o que viu. Usado ao trocar de partida ou de recorte."""
        self._last = None
        self._streak = 0
        self._confirmed = False
        self._misses = 0

    def scan(self, frame: np.ndarray | None) -> Match | None:
        """O melhor casamento deste quadro, sem olhar para o passado."""
        dados = _as_frame(frame)
        if dados is None or not self._templates:
            return None

        forma = (dados.shape[0], dados.shape[1])
        menor_lado = min(forma)
        # Um único conjunto de transformadas do quadro serve para todos
        # os tamanhos, já que os moldes são preenchidos até a forma dele.
        spectra = _frame_spectra(dados)

        melhor: Match | None = None
        for indice, molde in enumerate(self._templates):
            if molde.size > menor_lado:
                continue
            chave = (indice, forma)
            kernels = self._kernels.get(chave)
            if kernels is None:
                kernels = _template_spectra(molde, forma)
                self._kernels[chave] = kernels
            achado = _best(
                score_map(dados, molde, spectra=spectra, kernels=kernels),
                molde,
                self._threshold,
            )
            if achado is not None and (melhor is None or achado.score > melhor.score):
                melhor = achado
        return melhor

    def feed(self, frame: np.ndarray | None) -> Match | None:
        """Mais um quadro. Devolve o casamento só quando ele é confiável."""
        achado = self.scan(frame)
        if achado is None:
            # Quadro vazio antes da confirmação recomeça tudo; depois
            # dela, é o piscar normal do minimapa e vale a pena esperar
            # alguns quadros antes de dar o inimigo por perdido. Em
            # nenhum dos dois casos se devolve posição: não se viu nada.
            self._misses += 1
            if not self._confirmed or self._misses > self._forgive:
                self.reset()
            return None
        self._misses = 0

        if self._last is not None and self._near(achado, self._last):
            self._streak += 1
        else:
            # Longe do anterior: é outro evento, e a contagem recomeça.
            self._streak = 1
            self._confirmed = False

        self._last = achado
        if self._streak >= self._confirm:
            self._confirmed = True
        return achado if self._confirmed else None

    @staticmethod
    def _near(a: Match, b: Match) -> bool:
        limite = max(a.size, b.size) * JUMP_FRACTION
        return float(np.hypot(a.x - b.x, a.y - b.y)) <= limite
