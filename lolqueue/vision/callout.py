"""A frase que o app fala quando o jungler inimigo aparece.

Três coisas decidem o que é dito, nesta ordem de importância:

1. **Onde** ele apareceu — vem de `zones.classify`.
2. **De quem é aquele pedaço de mapa** — depende do lado do jogador, e é
   o que separa "na selva de cima" (fato) de "na sua selva de cima"
   (aviso).
3. **Quão perto ele está de você** — um jungler visto do outro lado do
   mapa é notícia boa e merece tom diferente de um visto atrás da sua
   torre.

O item 3 é o motivo de este módulo existir separado de `zones`: a mesma
zona significa coisas opostas para o jogador da rota de cima e para o da
rota de baixo, e falar como se todo mundo fosse o meio foi exatamente a
reclamação que originou este código.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from .livegame import BOT, JUNGLE, MID, SUPPORT, TOP, LiveGame
from .zones import Zone, classify, describe, well_inside

#: Perto o bastante para o jogador ter que reagir agora.
NEAR = 0.20

#: Longe o bastante para a notícia ser "pode empurrar tranquilo".
FAR = 0.48

#: Quanto tempo o mesmo aviso fica calado antes de poder repetir.
#: Sem isso o app vira um alarme de carro: o ícone some e volta a cada
#: quadro e a voz nunca fecha a boca.
REPEAT_SECONDS = 8.0

PERTO = "perto"
MEDIO = "medio"
LONGE = "longe"

#: Em que ponta do mapa cada rota vive. O meio não tem ponta: leva gank
#: dos dois lados, e para ele só a distância crua faz sentido.
LANE_END = {TOP: "top", BOT: "bot", SUPPORT: "bot"}


def map_end(wx: float, wy: float) -> str:
    """Metade do mapa no eixo Barão-Dragão.

    Serve para saber se o inimigo apareceu na sua ponta do mapa. É a
    mesma conta que separa rio de cima de rio de baixo em `zones`.
    """
    return "top" if wx + wy < 1.0 else "bot"


def proximity(distance: float) -> str:
    """Traduz distância em urgência."""
    if distance <= NEAR:
        return PERTO
    if distance >= FAR:
        return LONGE
    return MEDIO


@dataclass(frozen=True)
class Callout:
    """Um aviso pronto para falar."""

    text: str
    urgency: str
    zone_key: str
    # A metade do mapa em que a zona caiu. Vai junto da chave porque a
    # frase muda com ela — "na sua selva" e "na selva dele" partilham a
    # chave e dizem o contrário uma da outra.
    zone_side: int = 0
    # Se o ponto está longe o bastante das divisas para o nome valer.
    # Nasce verdadeiro para que um aviso montado à mão continue sendo
    # um aviso firme; só `announce` sabe medir isso.
    firm: bool = True

    def __str__(self) -> str:
        return self.text


def phrase(
    champion: str,
    zone: Zone,
    ally_side: int = 0,
    urgency: str = MEDIO,
) -> str:
    """Monta a frase falada.

    Fica sem dependência de partida de propósito, para poder ser testada
    sem o jogo aberto.
    """
    lugar = describe(zone, ally_side)
    nome = champion or "jungler inimigo"

    if urgency == PERTO:
        return f"Cuidado, {nome} {lugar}"
    if urgency == LONGE:
        return f"{nome} {lugar}, longe de você"
    return f"{nome} {lugar}"


#: Passo da varredura que descobre as zonas. Fino o bastante para não
#: pular nenhum campo da selva, que é o menor alvo do mapa.
_SWEEP = 90


@lru_cache(maxsize=1)
def zone_catalog() -> tuple[Zone, ...]:
    """Todas as zonas que `classify` é capaz de devolver.

    Descobertas varrendo o mapa, e não listadas à mão: `zones` monta
    várias delas na hora da classificação, e uma lista paralela sairia
    do ar no primeiro campo novo — em silêncio, e justamente na frase
    que não seria dita.
    """
    vistas: dict[tuple[str, int], Zone] = {}
    for i in range(_SWEEP + 1):
        for j in range(_SWEEP + 1):
            zona = classify(i / _SWEEP, j / _SWEEP)
            vistas.setdefault((zona.key, zona.side), zona)
    return tuple(vistas.values())


def all_phrases(champion: str, ally_side: int = 0) -> list[str]:
    """Tudo o que se pode dizer sobre este campeão nesta partida.

    Existe para a voz sintetizar antes, e não na hora: a síntese neural
    leva centenas de milissegundos, e esperar por ela com o inimigo já
    no rio é o mesmo que não avisar.

    A ordem importa porque a preparação leva alguns segundos e o gank
    pode chegar no meio dela: as frases do território do próprio jogador
    — as que evitam morte — saem primeiro.
    """
    saida: list[tuple[int, str]] = []
    vistos: set[str] = set()
    for zona in zone_catalog():
        minha = 0 if (zona.side != 0 and zona.side == ally_side) else 1
        for urgencia in (PERTO, MEDIO, LONGE):
            texto = phrase(champion, zona, ally_side, urgencia)
            if texto in vistos:
                continue
            vistos.add(texto)
            saida.append((minha, texto))
    saida.sort(key=lambda item: item[0])
    return [texto for _, texto in saida]


def announce(
    champion: str,
    mx: float,
    my: float,
    game: LiveGame | None = None,
) -> Callout:
    """O aviso completo para um ícone visto em (mx, my) no minimapa.

    Sem `game` o aviso ainda sai, só que neutro: melhor dizer "no rio de
    cima" do que ficar mudo porque a partida não respondeu.
    """
    if game is None:
        zona = classify(mx, my)
        return Callout(
            phrase(champion, zona), MEDIO, zona.key, zona.side, well_inside(mx, my)
        )

    # O minimapa pode estar girado 180° pela opção do jogo; o mundo não.
    wx, wy = game.to_world(mx, my)
    zona = classify(wx, wy)
    ax, ay = game.my_anchor
    urgencia = proximity(math.hypot(wx - ax, wy - ay))

    # Distância em linha reta mente no Rift: o mapa é um labirinto de
    # paredes, e o sapo do lado azul fica a 0.30 do topo em linha reta
    # mas a segundos de caminhada da rota de cima. A pergunta que
    # realmente importa é outra e é binária — o inimigo está na SUA
    # metade e na SUA ponta do mapa? Se está, o gank já começou.
    minha_ponta = LANE_END.get(game.lane)
    if minha_ponta is not None:
        if zona.side == game.side and map_end(wx, wy) == minha_ponta:
            urgencia = PERTO
    elif game.me.is_jungler:
        # Quem joga de jungler já vive na selva: avisar "cuidado" toda
        # vez que o inimigo pisa em mato não informa nada. Para ele a
        # metade inteira é casa e a pergunta é uma só — invadiram? E o
        # contrário também vale: encontrar o inimigo dentro da selva
        # dele é oportunidade, não perigo, mesmo estando ao lado.
        urgencia = PERTO if zona.side == game.side else MEDIO

    if game.anchor_is_a_guess:
        # Sem saber a rota do jogador, a distância foi medida a partir do
        # centro do mapa — um lugar onde ele provavelmente não está. Dizer
        # "longe de você" nessa conta é a pior saída possível: soa como
        # permissão para empurrar a rota no exato momento do gank. Sem
        # âncora, o aviso diz só onde o inimigo apareceu e deixa a leitura
        # com quem está vendo a tela.
        urgencia = MEDIO

    return Callout(
        phrase(champion, zona, game.side, urgencia),
        urgencia,
        zona.key,
        zona.side,
        well_inside(wx, wy),
    )
