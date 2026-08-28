"""Como se elege a melhor alternativa entre as que o OP.GG mediu.

Este módulo existe porque ordenar por taxa de vitória crua produz
conselho errado, e de dois jeitos diferentes que exigem correções
diferentes:

**Ruído de amostra.** "Banshee's Veil — 100% de vitórias" era o item
mais recomendado do 6º slot da Annie. Uma partida, uma vitória. Taxa
crua não sabe a diferença entre 100% de uma partida e 55% de mil.
Quem sabe é o limite inferior do intervalo de Wilson: ele pergunta
"qual é a pior taxa que esta amostra ainda sustenta com 95% de
confiança?", e uma amostra de uma partida não sustenta quase nada.

**Viés de sobrevivência.** Este o Wilson *não* corrige, e é o mais
perigoso porque parece dado sólido. O OP.GG mede a Ahri do meio com
Mejai's Soulstealer a 83,2% de vitória em 107 partidas — amostra
folgada para qualquer intervalo de confiança. Só que Mejai's é um item
que se compra *porque* a partida já está ganha: as 107 partidas não
são uma amostra da população, são uma amostra de quem já estava na
frente. A taxa mede o estado do jogo no momento da compra, não o
efeito do item. Contra isso não existe correção estatística — existe
piso de frequência: o que quase ninguém compra naquele slot foi
comprado pela situação, não pela build.

Por isso a eleição aqui é sempre dois filtros e um ranking: passa o
piso de amostra, passa o piso de escolha, e entre os que passaram
ganha o maior Wilson.

Módulo puro de propósito — sem Qt, sem rede, sem estado. Ele é o juiz
do arsenal inteiro (`opgg.py` e a leitura do confronto), e juiz que
depende de I/O não se testa direito.
"""

from __future__ import annotations

from math import sqrt
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")

#: Escore z de 95% de confiança bicaudal. É a convenção do gênero: a
#: U.GG e a Blitz publicam intervalo de 95%, e usar outro valor faria
#: os nossos números divergirem dos deles sem que a diferença fosse
#: visível para quem compara as duas telas.
Z = 1.96

#: Amostra mínima para uma alternativa disputar a eleição por taxa.
#:
#: O valor antigo era 30 — herdado da regra de bolso do teorema central
#: do limite, que diz quando a *aproximação normal* passa a valer, e
#: não quando a medida passa a significar alguma coisa. A 30 partidas o
#: intervalo de 95% em torno de 50% tem meia-largura de ±17,9 pontos:
#: a alternativa "de 60%" e a "de 45%" são estatisticamente a mesma
#: coisa, e ordenar entre elas é sortear.
#:
#: A 50 partidas a meia-largura cai para ±13,9 pontos. Ainda é larga,
#: mas é o ponto em que o intervalo deixa de ser mais largo do que a
#: faixa inteira onde as builds de verdade vivem (algo entre 48% e 57%
#: de vitória) — abaixo disso, qualquer ordenação é ruído com nome de
#: recomendação.
#:
#: Não subimos para as centenas que a U.GG usa por um motivo de dado, e
#: não de gosto: o piso da U.GG é por *página inteira*, com o universo
#: de partidas de um elo inteiro atrás. O que filtramos aqui é uma
#: alternativa de *um slot* — o 5º item de um campeão específico numa
#: rota específica —, e nesse recorte um slot inteiro raramente passa
#: de 300 partidas. Um piso de 100 não deixaria passar nenhuma
#: alternativa na maioria dos campeões, e o efeito prático não seria
#: rigor: seria o app sempre repetir a build mais jogada, que é
#: exatamente o problema que viemos consertar.
MIN_PLAYS = 50

#: Fração mínima do slot para uma alternativa ser considerada escolha
#: de build, e não escolha de situação.
#:
#: Este é o piso que barra o Mejai's. Um item comprado em menos de 10%
#: das partidas daquele slot não está sendo escolhido pela build: está
#: sendo escolhido por uma condição que já se realizou na partida
#: (estar na frente, o inimigo ser todo de dano físico, o jogo ter
#: passado dos 40 minutos). A taxa de vitória dele mede essa condição.
#:
#: 10% é onde a leitura vira outra: acima disso, a alternativa aparece
#: em uma a cada dez partidas do slot e é plausível como plano de
#: build; abaixo, é resposta a um cenário que quem lê a recomendação
#: antes da partida não tem como saber se vai acontecer.
MIN_PICK_RATE = 0.10


def wilson_lower(wins: int, plays: int, z: float = Z) -> float:
    """O limite inferior do intervalo de Wilson para uma proporção.

    Devolve a pior taxa de vitória que a amostra ainda sustenta com a
    confiança pedida. É isso que faz 100% de uma partida (0,207) perder
    para 55% de mil (0,519): a amostra pequena paga a incerteza dela.

    `plays` zerado devolve 0,0 em vez de estourar — campo vazio é caso
    normal na resposta do OP.GG, não erro de programação.
    """
    if plays <= 0:
        return 0.0
    proportion = wins / plays
    denominator = 1 + z * z / plays
    center = proportion + z * z / (2 * plays)
    margin = z * sqrt(proportion * (1 - proportion) / plays + z * z / (4 * plays * plays))
    return max(0.0, (center - margin) / denominator)


def score(win_rate: float, plays: int, z: float = Z) -> float:
    """`wilson_lower` para quem guardou a taxa em vez do total de vitórias.

    O resto do app modela as alternativas com `win_rate` (é o que a
    loja e a UI mostram), então converter de volta aqui evita carregar
    o mesmo número em dois campos. `win_rate * plays` reconstrói o
    total exato, porque a taxa nasceu justamente dessa divisão.
    """
    return wilson_lower(round(win_rate * plays), plays, z)


def solid(
    plays: int,
    pick_rate: float,
    min_plays: int = MIN_PLAYS,
    min_pick_rate: float = MIN_PICK_RATE,
) -> bool:
    """Se esta alternativa tem direito a disputar a eleição por taxa.

    Os dois pisos respondem a problemas distintos e nenhum dos dois
    substitui o outro: o de amostra barra o ruído, o de frequência
    barra o viés de sobrevivência. O Mejai's passa no primeiro com
    folga e é barrado pelo segundo.
    """
    return plays >= min_plays and pick_rate >= min_pick_rate


def ranked(
    options: Iterable[T],
    sample: Callable[[T], tuple[float, int, float]],
    min_plays: int = MIN_PLAYS,
    min_pick_rate: float = MIN_PICK_RATE,
) -> list[T]:
    """As alternativas que passaram nos pisos, da melhor para a pior.

    `sample` extrai `(win_rate, plays, pick_rate)` do que quer que o
    chamador esteja ordenando — bloco de item, página de runa, feitiço.
    O módulo não conhece nenhum desses tipos de propósito: ele julga
    amostras, e quem tem amostra é assunto de quem chama.

    O desempate por `plays` importa mais do que parece: duas
    alternativas podem empatar no Wilson arredondado, e sem critério
    estável a ordem viraria a de inserção — o que faria a mesma
    consulta devolver arsenais diferentes conforme o servidor
    reordenasse a resposta.
    """
    qualified = [
        option for option in options if solid(*sample(option)[1:], min_plays, min_pick_rate)
    ]
    return sorted(
        qualified,
        key=lambda option: (score(sample(option)[0], sample(option)[1]), sample(option)[1]),
        reverse=True,
    )


def best(
    options: Sequence[T],
    sample: Callable[[T], tuple[float, int, float]],
    min_plays: int = MIN_PLAYS,
    min_pick_rate: float = MIN_PICK_RATE,
) -> T | None:
    """A melhor alternativa sustentada pelos dados, ou ``None``.

    ``None`` quando nenhuma passa nos pisos, e é resposta de propósito:
    quem chama decide se repete a mais jogada (é o que o arsenal faz —
    a mais jogada é a única leitura que uma amostra fraca ainda
    sustenta) ou se esconde o slot. Devolver a melhor entre as
    reprovadas seria dar o nome de recomendação a um sorteio.
    """
    winners = ranked(options, sample, min_plays, min_pick_rate)
    return winners[0] if winners else None
