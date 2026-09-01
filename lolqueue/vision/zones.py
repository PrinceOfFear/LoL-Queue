"""Transformar um ponto do mapa no nome de um lugar.

O mapa do LoL é um quadrado girado: as duas bases ficam em cantos
opostos, a rota do meio é a diagonal entre elas e o rio é a outra
diagonal. Descrever esse desenho com caixas alinhadas aos eixos — que
foi a primeira tentativa, herdada de outro projeto — dá errado de um
jeito específico: as caixas se sobrepõem, um mesmo ponto cai em "perto
do Barão" e em "rota do topo" ao mesmo tempo, e quem responde é quem
estiver primeiro na lista.

Aqui o mapa é lido no sistema em que ele foi desenhado, girado 45°:

    avanço = x + y   → 1 é a linha do meio; abaixo é o lado do Barão,
                       acima é o lado do Dragão
    lado   = y - x   → positivo é a metade azul, negativo a vermelha

Nesse sistema "rio", "rota do meio" e "metade do mapa" viram comparações
de um número só. A classificação vai da pista mais específica para a
mais genérica: objetivo tem nome próprio, rota tem nome, e o que sobra é
selva — que sempre responde, porque ficar em silêncio por não saber
nomear é o pior resultado possível para quem está prestes a levar gank.

As coordenadas seguem a orientação canônica de `minimap.to_map`:
(0, 1) é a base azul e (1, 0) a vermelha.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Quão perto do canto ainda é base. A área anterior alcançava 39 px num
#: minimapa de 280 px e chamava de base a saída dela; a zona curta prefere
#: uma descrição genérica a localizar o jungler dentro da fonte inimiga sem
#: prova suficiente.
BASE_RADIUS = 0.105

#: Raio dos objetivos. O antigo 0,10 encostava no red mais próximo e
#: chegava a engolir parte do campo. 0,075 deixa uma faixa honesta de
#: selva entre o covil e os acampamentos vizinhos.
OBJECTIVE_RADIUS = 0.075

#: Largura de meia rota. O caminho desenhado no minimapa é estreito; fora
#: deste corredor a frase "na rota" vira palpite sobre alguém na selva.
LANE_HALF_WIDTH = 0.047

#: Meia largura do rio, medida a partir da diagonal.
RIVER_HALF_WIDTH = 0.052

#: Distância do corredor das rotas laterais até a borda do mapa.
SIDE_LANE_OFFSET = 0.075

#: Onde ficam os poços dos objetivos, sobre a diagonal do rio.
BARON_PIT = (0.34, 0.30)
DRAGON_PIT = (0.66, 0.70)

#: Centro das bases.
BLUE_BASE = (0.12, 0.88)
RED_BASE = (0.88, 0.12)

#: Abaixo disso em |y - x| o ponto está em cima da linha do rio e não
#: pertence a metade nenhuma do mapa.
NEUTRAL_BAND = 0.04

_SQRT2 = math.sqrt(2.0)

#: Raio de um campo da selva. Blue e lobos, os vizinhos mais próximos,
#: ficam a 0,100 do mapa um do outro. O antigo raio 0,055 fazia os
#: círculos se sobreporem; 0,045 deixa um corredor entre eles para que um
#: ponto ambíguo caia em "selva" em vez de receber o nome do primeiro campo
#: que a lista examinou.
CAMP_RADIUS = 0.045

#: Os seis campos de cada metade, com o nome que o jogador brasileiro
#: usa de verdade. Ninguém fala "Rubrivira" nem "Acuáminas": fala red e
#: galinhas. As posições vêm das coordenadas de mundo do Rift, que é
#: simétrico por rotação de 180° — cada campo do lado vermelho é o
#: espelho exato do azul em torno do centro do mapa.
_CAMPOS_AZUIS = (
    # chave,     x,     y,     label,              minha,               dele
    ("gromp",    0.146, 0.435, "no sapo",          "no seu sapo",       "no sapo dele"),
    ("blue",     0.258, 0.467, "no blue",          "no seu blue",       "no blue dele"),
    ("wolves",   0.256, 0.567, "nos lobos",        "nos seus lobos",    "nos lobos dele"),
    ("raptors",  0.472, 0.637, "nas galinhas",     "nas suas galinhas", "nas galinhas dele"),
    ("red",      0.526, 0.731, "no red",           "no seu red",        "no red dele"),
    ("krugs",    0.567, 0.825, "nas pedrinhas",    "nas suas pedrinhas", "nas pedrinhas dele"),
)


def _campos() -> tuple[tuple[str, float, float, int, str, str, str], ...]:
    """Os doze campos, os seis azuis mais os seis espelhados."""
    saida = []
    for chave, x, y, label, minha, dele in _CAMPOS_AZUIS:
        saida.append((chave, x, y, 1, label, minha, dele))
        saida.append((chave, 1.0 - x, 1.0 - y, -1, label, minha, dele))
    return tuple(saida)


CAMPS = _campos()



@dataclass(frozen=True)
class Zone:
    """Um lugar com nome.

    `label` é escrito para caber depois de "visto": "visto no rio de
    cima".

    `mine`/`theirs` são a mesma frase quando se sabe de quem é o
    território. São duas frases prontas, e não um molde com possessivo,
    porque o português não encaixa o possessivo em posição fixa: "na sua
    selva de cima", mas "na base dele". Escrever as duas custa uma linha
    por zona e evita as frases tortas que uma regra genérica produziria.
    """

    key: str
    label: str
    #: Metade do mapa a que pertence: 1 azul, -1 vermelha, 0 neutra.
    side: int = 0
    mine: str = ""
    theirs: str = ""

    @property
    def ally_relative(self) -> bool:
        """Se a frase muda conforme o time de quem escuta."""
        return bool(self.mine and self.theirs)


#: Zonas sem dono: valem o mesmo para os dois times.
MID = Zone("mid", "na rota do meio")
BARON = Zone("baron", "no covil do Barão")
DRAGON = Zone("dragon", "no covil do Dragão")
RIVER_TOP = Zone("river_top", "no rio de cima")
RIVER_BOT = Zone("river_bot", "no rio de baixo")


def _distance(point: tuple[float, float], other: tuple[float, float]) -> float:
    return math.hypot(point[0] - other[0], point[1] - other[1])


def _side_of(mx: float, my: float) -> int:
    """Em que metade do mapa o ponto está."""
    lado = my - mx
    if lado > NEUTRAL_BAND:
        return 1
    if lado < -NEUTRAL_BAND:
        return -1
    return 0


def classify(mx: float, my: float) -> Zone:
    """O lugar onde o ponto (mx, my) está.

    Sempre devolve alguma coisa: a última regra cobre o mapa inteiro.
    """
    avanco = mx + my
    lado = _side_of(mx, my)

    # 1. Bases primeiro: elas ficam nas pontas da rota do meio e seriam
    #    engolidas por ela.
    if _distance((mx, my), BLUE_BASE) <= BASE_RADIUS:
        return Zone("blue_base", "na base azul", 1, "na sua base", "na base dele")
    if _distance((mx, my), RED_BASE) <= BASE_RADIUS:
        return Zone("red_base", "na base vermelha", -1, "na sua base", "na base dele")

    # 2. Objetivos têm nome próprio e ganham de rio e de selva.
    if _distance((mx, my), BARON_PIT) <= OBJECTIVE_RADIUS:
        return BARON
    if _distance((mx, my), DRAGON_PIT) <= OBJECTIVE_RADIUS:
        return DRAGON

    # 3. Campos da selva. Vêm antes das rotas de propósito: quem está
    #    no blue está no blue, mesmo que o blue caia perto da rota.
    for chave, cx, cy, dono, label, minha, dele in CAMPS:
        if _distance((mx, my), (cx, cy)) <= CAMP_RADIUS:
            return Zone(chave, label, dono, minha, dele)

    # 4. Rotas. A do meio é a diagonal; as laterais correm coladas às
    #    bordas, em L, e por isso são testadas como duas retas.
    if abs(avanco - 1.0) / _SQRT2 <= LANE_HALF_WIDTH:
        return MID
    borda = SIDE_LANE_OFFSET + LANE_HALF_WIDTH
    if (mx <= borda and my < 1.0 - borda) or (my <= borda and mx < 1.0 - borda):
        return Zone(
            "top_lane",
            "na rota de cima",
            lado,
            "na rota de cima, do seu lado",
            "na rota de cima, do lado dele",
        )
    if (mx >= 1.0 - borda and my > borda) or (my >= 1.0 - borda and mx > borda):
        return Zone(
            "bot_lane",
            "na rota de baixo",
            lado,
            "na rota de baixo, do seu lado",
            "na rota de baixo, do lado dele",
        )

    # 5. Rio: perto da outra diagonal, e já descartados os objetivos.
    if abs(my - mx) / _SQRT2 <= RIVER_HALF_WIDTH:
        return RIVER_TOP if avanco < 1.0 else RIVER_BOT

    # 6. Selva. Cobre todo o resto, nos quatro quadrantes que os
    #    jogadores de fato usam para se orientar.
    if avanco < 1.0:
        return Zone(
            "jungle_top",
            "na selva de cima",
            lado,
            "na sua selva de cima",
            "na selva de cima dele",
        )
    return Zone(
        "jungle_bot",
        "na selva de baixo",
        lado,
        "na sua selva de baixo",
        "na selva de baixo dele",
    )


# Quanto o ponto precisa estar para DENTRO de uma zona para o nome dela
# valer como firme. Em um minimapa de 280 px são 4,5 px de folga: maior
# que o tremor normal do casamento, menor que a distância entre campos.
STABLE_MARGIN = 0.016


def place(mx: float, my: float) -> tuple[str, int]:
    """A identidade falada do lugar: o nome e de quem é a metade.

    `key` sozinha não basta para saber se a frase mudou: "na sua selva
    de cima" e "na selva de cima dele" têm a mesma chave e são avisos
    opostos. Quem compara dois quadros tem que comparar os dois campos.
    """
    zona = classify(mx, my)
    return zona.key, zona.side


def well_inside(
    mx: float,
    my: float,
    margin: float = STABLE_MARGIN,
    probes: int = 8,
) -> bool:
    """Se o ponto está a mais de `margin` de qualquer divisa.

    O mapa tem 29 zonas e um terço da área dele fica a menos de 0.02 de
    uma divisa. Em cima de uma, o tremor normal do casamento de imagem —
    um ou dois pixels — troca o nome do lugar sem o campeão ter andado
    nada, e a voz descreve uma corrida que não aconteceu. Medindo o
    trajeto de um jungler por dez minutos, o app dizia de quatro a doze
    vezes mais nomes diferentes do que o campeão de fato visitou.

    A divisa não pode ser detectada olhando um ponto só: é preciso
    perguntar o que tem em volta. Oito sondas igualmente espaçadas a
    `margin` de distância cobrem retas, diagonais e as bordas circulares
    de campo e objetivo. O modo de precisão máxima pede dezesseis:
    entre duas sondas ainda existe uma pequena fresta em uma curva, e
    nela a resposta honesta é esperar em vez de nomear o vizinho.

    0.016 do mapa são cerca de 240 unidades do Rift: folga bastante para
    não chamar um vizinho de acampamento, sem transformar o mapa inteiro
    em área morta.
    """
    aqui = place(mx, my)
    # Menos de quatro sondas deixa qualquer uma das quatro direções
    # principais descoberta; valor torto vindo de um chamador não pode
    # transformar "firme" em uma aposta.
    try:
        count = max(4, int(probes))
    except (TypeError, ValueError):
        count = 8
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        dx = margin * math.cos(angle)
        dy = margin * math.sin(angle)
        if place(mx + dx, my + dy) != aqui:
            return False
    return True


def describe(zone: Zone, ally_side: int = 0) -> str:
    """A zona dita do ponto de vista do jogador.

    `ally_side` é 1 para quem joga de azul, -1 de vermelho e 0 quando
    ainda não se sabe. Saber de quem é o território muda a frase de
    informativa para acionável: "na selva de cima" é um fato, "na sua
    selva de cima" é um aviso.
    """
    if not zone.ally_relative or zone.side == 0 or ally_side == 0:
        return zone.label
    return zone.mine if zone.side == ally_side else zone.theirs
