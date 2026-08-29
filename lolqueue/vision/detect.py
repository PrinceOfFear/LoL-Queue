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

#: O quanto o melhor ponto do quadro precisa ganhar do segundo melhor
#: ponto distinto — a "folga" do casamento.
#:
#: Esta é a defesa que faltava, e a falta dela é o que enchia a partida
#: de aviso falso. Um minimapa de 470 px dá quase duzentas mil posições
#: por molde, e três moldes por quadro: meio milhão de sorteios. Entre
#: meio milhão de pedaços de terreno sempre há um que se parece com o
#: retrato mais do que 0,85, e o limiar absoluto não tem como saber que
#: aquele foi só o melhor de muitos. Pior: o terreno não anda, então o
#: mesmo pedaço vence quadro após quadro e a confirmação de três
#: quadros — que existe para pegar brilho passageiro — carimba o erro
#: em vez de barrá-lo.
#:
#: Medido contra o desenho do mapa 11 com nevoeiro, ruído e nove ícones
#: espalhados: com o ícone presente a folga ficou entre 0,12 e 0,18;
#: sem ele, nunca passou de 0,04.
#:
#: Aquele "nunca passou de 0,04" não sobreviveu a uma medição melhor. O
#: desenho do mapa 11 é chapado; refeita a conta sobre um fundo com a
#: textura da arte de verdade do jogo — retratos reais em cache como
#: distratores, oito alvos ausentes, três sementes, 1440 quadros — a
#: folga do terreno chegou a 0,138, e passou de 0,10 em quatro dos
#: vinte e quatro casos. Ou seja: a folga NÃO fica acima de todo
#: terreno, e não é ela que segura o caso ausente.
#:
#: Quem segura é o limiar absoluto. Nos mesmos 1440 quadros sem o alvo,
#: nenhum pico cru passou de 0,635 contra `THRESHOLD` de 0,85, e a
#: contagem de confirmados foi zero em todas as configurações. A folga
#: continua valendo o que sempre valeu — desempatar entre pontos
#: parecidos do MESMO quadro — mas o número dela é uma escolha de
#: rigor, não uma linha traçada entre duas populações separadas.
#:
#: A folga também se ajusta sozinha ao quadro, o que o limiar absoluto
#: não faz: nevoeiro e borrão derrubam o pico do ícone, mas derrubam
#: junto o chão de terreno contra o qual ele é comparado.
MARGIN = 0.06

#: O que conta como "o mesmo pico", em frações do lado do molde. Serve
#: para o segundo lugar não ser o pixel vizinho do primeiro: a
#: correlação de um ícone de verdade é um morro, não uma agulha, e
#: medir a folga contra a encosta do próprio morro daria zero sempre.
PEAK_RADIUS = 1.0

#: Quantos quadros seguidos precisam concordar antes do aviso sair. Um
#: casamento solto pode ser um brilho passageiro; três em sequência, no
#: mesmo lugar, não.
CONFIRM_FRAMES = 3

#: O quanto o ícone pode ter andado entre dois quadros e ainda ser o
#: mesmo ícone, em frações do próprio lado. Dois casamentos em pontas
#: opostas do mapa são dois eventos, e contá-los juntos deixaria um
#: falso positivo virar aviso.
#:
#: Um lado inteiro por quadro era folga demais e enfraquecia a
#: confirmação sem que ninguém pedisse: a cinco quadros por segundo dá
#: 175 px por segundo num minimapa de 470, um campeão cruzando o mapa
#: em menos de três segundos. Ninguém anda assim — 400 unidades por
#: segundo, que é a velocidade de um campeão rápido, valem uns 13 px
#: por segundo nessa escala, e um Flash inteiro vale 13 px de uma vez.
#: Metade do lado ainda é sete vezes o movimento real, o bastante para
#: o centro do casamento tremer entre tamanhos de molde e para os dois
#: quadros de perdão, e apertado o suficiente para dois falsos
#: positivos distantes não virarem um só evento.
JUMP_FRACTION = 0.5

#: Quantos quadros vazios seguidos um casamento já confirmado sobrevive.
#: O ícone do inimigo pisca o tempo todo — o nevoeiro cobre por um
#: instante, um clarão estoura por cima, outro ícone passa na frente — e
#: esquecer tudo no primeiro quadro vazio cobrava três quadros novos,
#: mais de meio segundo, para voltar a falar de alguém que nunca saiu do
#: lugar. Num aviso de gank, meio segundo é a diferença entre recuar e
#: morrer. Antes da confirmação nada é perdoado: é lá que mora a defesa
#: contra o falso positivo, e ela fica exatamente como era.
FORGIVE_FRAMES = 2

#: A folga exigida de um casamento que não tem rastro a que se agarrar:
#: o primeiro da partida, ou um que apareceu longe demais do anterior
#: para ser o mesmo campeão andando.
#:
#: É a mesma medida de `MARGIN` respondendo a outra pergunta, e por isso
#: o número é outro. `MARGIN` decide se vale a pena continuar olhando
#: para um ponto; aqui se decide para onde o rastro vai apontar, e errar
#: aqui não atrasa um aviso: inventa um. O terreno não anda, então um
#: pedaço de mato que vença o argmax enquanto o ícone está sob o
#: nevoeiro vira um rastro confirmado do outro lado do mapa, e o app
#: aponta gank onde não há ninguém — que é exatamente o aviso errado
#: que o jogador ouvia.
#:
#: Contra o desenho do mapa 11 com nevoeiro, ruído e nove ícones
#: espalhados, o retrato de verdade mediu folga de 0,12 a 0,18 e o
#: terreno nunca passou de 0,04 — mas ver a ressalva em `MARGIN`: sobre
#: um fundo com textura de arte real o terreno chegou a 0,138, e 0,10
#: não fica acima de todo terreno medido. O que mantém o caso ausente
#: mudo é `THRESHOLD`; este número aperta a aquisição, não a garante.
#:
#: Enquanto o rastro existe a exigência volta a ser `MARGIN`: um ícone
#: já acompanhado pode perder folga por causa do nevoeiro sem deixar de
#: ser ele. Adquirir com rigor e acompanhar com folga é a diferença
#: entre este detector e o anterior.
ACQUIRE_MARGIN = 0.10

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
    #: Quanto este ponto ganhou do segundo melhor ponto do quadro.
    margin: float = 0.0


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


def _runner_up(mapa: np.ndarray, y: int, x: int, size: int) -> float | None:
    """O melhor ponto do quadro fora da vizinhança do pico.

    Devolve `None` quando não sobra quadro nenhum para olhar — recorte
    quase do tamanho do molde —, que é diferente de "o resto é ruim".

    As quatro faixas em volta da caixa excluída evitam copiar o mapa
    inteiro cinco vezes por segundo, e evitam também mexer no mapa de
    quem chamou.
    """
    raio = max(1, int(round(size * PEAK_RADIUS)))
    altura, largura = mapa.shape
    y0, y1 = max(0, y - raio), min(altura, y + raio + 1)
    x0, x1 = max(0, x - raio), min(largura, x + raio + 1)
    faixas = (mapa[:y0, :], mapa[y1:, :], mapa[y0:y1, :x0], mapa[y0:y1, x1:])
    valores = [float(faixa.max()) for faixa in faixas if faixa.size]
    return max(valores) if valores else None


def _best(
    mapa: np.ndarray | None,
    template: Template,
    threshold: float,
    margin: float = MARGIN,
) -> Match | None:
    if mapa is None or mapa.size == 0:
        return None
    plano = int(np.argmax(mapa))
    y, x = divmod(plano, mapa.shape[1])
    valor = float(mapa[y, x])
    if valor < threshold:
        return None
    segundo = _runner_up(mapa, y, x, template.size)
    # Sem segundo lugar não há com o que comparar, e exigir folga de um
    # quadro que só tem uma posição seria recusar por falta de prova
    # que ninguém podia dar.
    folga = valor if segundo is None else valor - segundo
    if folga < margin:
        return None
    meio = template.size // 2
    return Match(
        x=int(x) + meio,
        y=int(y) + meio,
        score=valor,
        size=template.size,
        margin=folga,
    )


def match_template(
    frame: np.ndarray | None,
    template: Template,
    threshold: float = THRESHOLD,
    margin: float = MARGIN,
) -> Match | None:
    """A melhor posição do molde no quadro, se passar do limiar."""
    return _best(score_map(frame, template), template, threshold, margin)


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
        margin: float = MARGIN,
        acquire: float = ACQUIRE_MARGIN,
    ) -> None:
        self._templates = [t for t in templates if t.size >= 1]
        self._threshold = float(threshold)
        self._margin = float(margin)
        self._acquire = max(float(margin), float(acquire))
        self._confirm = max(1, int(confirm))
        self._forgive = max(0, int(forgive))
        self._kernels: dict[tuple[int, tuple[int, int]], _Kernels] = {}
        self._last: Match | None = None
        self._streak = 0
        self._confirmed = False
        self._misses = 0
        # Qual molde venceu o último quadro, e qual deles ficou preso
        # depois da confirmação. O ícone não muda de tamanho no meio da
        # partida, então continuar varrendo os três é pagar três vezes
        # pelo mesmo resultado — e dar duas chances a mais para um pico
        # de terreno em escala errada roubar o rastro.
        self._winner: int | None = None
        self._locked: int | None = None

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
        self._winner = None
        self._locked = None

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

        alvos = list(enumerate(self._templates))
        if self._locked is not None and self._locked < len(self._templates):
            alvos = [(self._locked, self._templates[self._locked])]

        melhor: Match | None = None
        vencedor: int | None = None
        for indice, molde in alvos:
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
                self._margin,
            )
            if achado is not None and (melhor is None or achado.score > melhor.score):
                melhor, vencedor = achado, indice
        self._winner = vencedor
        return melhor

    def feed(self, frame: np.ndarray | None) -> Match | None:
        """Mais um quadro. Devolve o casamento só quando ele é confiável."""
        achado = self.scan(frame)
        if achado is not None and not self._plausible(achado):
            # Casou, mas longe do rastro e sem folga que prove ser ele.
            # É o terreno vencendo o argmax enquanto o ícone está sob o
            # nevoeiro, e isso vale como quadro vazio — nunca como troca
            # de alvo. Trocar era como o aviso ia parar do outro lado do
            # mapa, e era como um quadro solto derrubava uma confirmação
            # que custou mais de meio segundo para juntar.
            achado = None
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
            self._locked = self._winner
        return achado if self._confirmed else None

    def _plausible(self, achado: Match) -> bool:
        """Se este casamento pode mesmo ser o campeão que se acompanha.

        Duas saídas, e a diferença entre elas é ter passado ou não. Se
        o ponto cabe no que o ícone teria conseguido andar desde a
        última vez que foi visto, ele é a continuação do rastro e basta
        a folga de sempre. Se não cabe — o primeiro da partida, um
        Flash, um retorno à base, ou terreno se passando por gente —
        não há continuidade nenhuma a favor dele, e aí a prova tem que
        vir inteira da folga.
        """
        if self._last is not None and self._near(achado, self._last, self._misses):
            return True
        return achado.margin >= self._acquire

    @staticmethod
    def _near(a: Match, b: Match, blind: int = 0) -> bool:
        """Se os dois casamentos podem ser o mesmo ícone.

        `blind` são os quadros vazios entre um e outro: quem passou um
        instante sob o nevoeiro reaparece mais longe de onde sumiu, e
        cobrar dele o passo de um quadro só transformaria cada piscada
        do minimapa em um alvo novo.
        """
        limite = max(a.size, b.size) * JUMP_FRACTION * (1 + max(0, int(blind)))
        return float(np.hypot(a.x - b.x, a.y - b.y)) <= limite
