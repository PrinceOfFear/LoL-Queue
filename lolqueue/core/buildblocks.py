"""O degrau da lista de compra, com as alternativas que se sustentam.

Os dois lados da recomendação — o boletim do campeão (`opgg`) e o guia
do confronto (`matchup`) — chegam ao mesmo lugar: para cada compra, o
OP.GG mede várias opções e alguém precisa decidir quais delas o jogador
vê na loja. A regra era escrita duas vezes, e as duas versões
divergiram: o guia mostrava três alternativas por degrau e o boletim
mostrava uma só, escondendo justamente a variação que dá liberdade de
adaptar o build à partida.

Aqui ela existe uma vez. Nada neste módulo conhece as estruturas dos
dois lados: o bloco de saída nasce de `dataclasses.replace` sobre o
líder do degrau, então serve a qualquer dataclass com `items`,
`win_rate`, `games` e `pick_rate`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, TypeVar

from . import ranking


@dataclass(frozen=True)
class Block:
    """Um bloco do arsenal: o rótulo na loja e o que comprar nele.

    `games` é o tamanho da amostra que mediu este bloco, e existe para
    ordenar alternativas. Sem ele a ordem sairia por taxa de vitória
    pura, e um item de três partidas com 100% passaria na frente do que
    todo mundo compra — conselho fabricado a partir de ruído.

    `pick_rate` é a fatia das partidas em que a alternativa foi
    escolhida. Ela separa a compra padrão da compra de nicho quando as
    taxas empatam, e é o terceiro piso que `ranking` cobra.
    """

    label: str
    items: tuple[int, ...]
    win_rate: float
    games: int = 0
    pick_rate: float = 0.0

#: Quantas alternativas cabem num degrau. Três é o que o OP.GG mede com
#: amostra que se sustente, e é o que os apps do gênero mostram lado a
#: lado: a compra padrão e as duas saídas para quando a partida pede
#: outra coisa. A quarta já é ruído — pick rate de um dígito e amostra
#: que não distingue build de acaso.
MAX_ALTERNATIVES = 3

B = TypeVar("B")


def sample(block) -> tuple[float, int, float]:
    """O bloco visto como amostra, que é a linguagem de `ranking`."""
    return (block.win_rate, block.games, block.pick_rate)


def slot(
    options: list[B],
    bought: set[int],
    limit: int = MAX_ALTERNATIVES,
) -> B | None:
    """Um degrau da lista de compra: as alternativas que se sustentam.

    Quatro regras, cada uma respondendo a um estrago já visto na tela:

    1. Passa quem `ranking` aprova — limite inferior de Wilson, piso de
       amostra e piso de frequência de escolha.
    2. Quando ninguém passa, o degrau repete a alternativa mais jogada.
       É a única leitura que uma amostra fraca ainda sustenta, e é
       melhor que um buraco no meio da ordem de compra.
    3. O que um degrau anterior mandou **comprar** não volta. Só o
       primeiro item de cada degrau — o recomendado — entra em
       `bought`; as alternativas ficam livres para reaparecer no degrau
       seguinte, e é isso que as torna alternativas. A regra antiga
       reservava as três, e o efeito na loja era o degrau seguinte
       sumir inteiro: o 4º item da Ahri levava Zhonya's, Rabadon's e
       Void Staff, e o 5º ficava sem nenhuma opção para oferecer.
    4. Sobrando nada depois desse corte, o degrau some. Bloco vazio na
       loja é pior que um degrau a menos.

    A ordem dentro do bloco é a de `ranking`, não a de uso: o primeiro
    é o que os dados sustentam melhor, e os seguintes são as saídas.
    Taxa e fatia ficam sendo as do primeiro — média das três seria um
    número que não descreve nenhuma das compras que o jogador pode
    fazer.

    Repetição *dentro* de uma alternativa sobrevive: duas Poções de
    Vida no bloco inicial são duas poções, e a loja as mostra como
    "x2". O que não se repete é o item que já veio de outra
    alternativa.

    `bought` é lido **e** atualizado; quem chama percorre os degraus na
    ordem de compra e o conjunto carrega o que já saiu.
    """
    if not options:
        return None
    chosen = list(ranking.ranked(options, sample))[:limit]
    if not chosen:
        chosen = [max(options, key=lambda block: block.games)]
    items: list[int] = []
    leader: B | None = None
    for block in chosen:
        taken_here = set(block.items)
        if taken_here & bought or taken_here & set(items):
            continue
        if leader is None:
            leader = block
            bought.update(block.items)
        items.extend(block.items)
    if leader is None:
        return None
    return replace(leader, items=tuple(items))


def taken(blocks: Iterable) -> set[int]:
    """Tudo o que os blocos já mandaram comprar, pronto para `slot`."""
    return {item for block in blocks for item in block.items}
