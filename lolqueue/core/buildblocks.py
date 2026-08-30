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

#: Amostra mínima para a repescagem valer. Quando ninguém passa nos
#: pisos de `ranking`, o degrau repete a alternativa mais jogada — e
#: sem um piso aqui "mais jogada" chegou a significar *duas partidas*.
#: Medido contra o servidor no elo Desafiante: o 6º item da Ashe saía
#: Cimitarra Mercurial com 2 partidas e 0 vitórias, e o da Ahri saía
#: Chama Sombria com 1. Ambos entravam na loja com a mesma cara de
#: recomendação que o item de mil partidas.
#:
#: Dez é baixo de propósito: a repescagem ordena por *popularidade*, e
#: popularidade se mede com muito menos amostra que taxa de vitória —
#: por isso não reaproveita o `MIN_PLAYS` de `ranking`, que existe para
#: julgar taxa. O que dez barra é o ruído puro; a cauda legítima de um
#: 5º item (170 partidas no Darius de Diamante+) passa folgada.
MIN_FALLBACK_PLAYS = 10

#: O que se compra de novo a cada volta à base, e por isso não ocupa
#: vaga: poções, biscoitos, frascos, elixires e os três totens.
#:
#: A regra antiga era mais grossa — os degraus de iniciais e botas
#: ficavam *inteiros* fora do controle de repetidos, com o argumento de
#: que consumível se recompra. O efeito colateral era o item inicial
#: permanente reaparecer no núcleo: a Lágrima da Deusa do Nautilus
#: saía em "Iniciais" e de novo em "Principais", mandando comprar duas.
#: Agora quem escapa da reserva é o consumível, não o degrau.
CONSUMABLES = frozenset(
    {
        2003,  # Poção de Vida
        2010,  # Biscoito Total
        2031,  # Frasco Reabastecível
        2033,  # Frasco Corrompido
        2052,  # Poro-Snax
        2055,  # Biscoito Sem Fim
        2138,  # Elixir de Ferocidade
        2139,  # Elixir de Feitiçaria
        2140,  # Elixir de Ferro
        3340,  # Totem Vigilante
        3363,  # Orbe Anunciador
        3364,  # Totem Oráculo
    }
)

#: Itens de começo, que nunca são conselho para o fim da partida.
#:
#: O bloco de situacionais nasce do `last_items` do OP.GG, que é o
#: ranking dos itens *mais construídos* do campeão — e o mais
#: construído de um mago costuma ser o que ele compra aos quatro
#: minutos. Na Ahri de Mestre+ a lista saía `(Bastão Rúnico, Lacre
#: Sombrio)`: 350 de ouro oferecidos como saída para o fim de jogo,
#: quando o jogador já vendeu o dele há vinte minutos.
#:
#: O corte é por *função*, não por preço: o que está aqui só faz
#: sentido comprado cedo, seja porque escala com um acúmulo que não
#: começa mais (Lacre, Cull), porque a passiva de regeneração paga a
#: fase de rota (Doran, bichinhos da selva) ou porque é a primeira
#: pedra de uma linha que a build já subiu (Lágrima, item de suporte).
#: Preços conferidos no catálogo do Data Dragon 16.17.1.
#:
#: Os itens de suporte *completos* — Trenó do Solstício, Oposição
#: Celestial e companhia — ficam de fora deste corte de propósito:
#: escolher entre eles é decisão de verdade, e é a única decisão de
#: compra que sobra para um suporte no fim da partida.
EARLY_ONLY = frozenset(
    {
        1054,  # Escudo de Doran (450)
        1055,  # Lâmina de Doran (450)
        1056,  # Anel de Doran (400)
        1082,  # Lacre Sombrio (350)
        1083,  # Cull (450)
        1101,  # Filhote Garra-em-Brasa (450)
        1102,  # Filhote Andarrajada (450)
        1103,  # Broto Pisa-Musgo (450)
        3070,  # Lágrima da Deusa (400)
        3850,  # Gume do Ladrão de Feitiços (400)
        3854,  # Ombreiras de Aço (400)
        3858,  # Escudo Relicário (400)
        3862,  # Foice Espectral (400)
        3865,  # Atlas do Mundo (400)
        3866,  # Bússola Rúnica (400)
        3867,  # Prêmio dos Mundos (400)
    }
)

B = TypeVar("B")


def sample(block) -> tuple[float, int, float]:
    """O bloco visto como amostra, que é a linguagem de `ranking`."""
    return (block.win_rate, block.games, block.pick_rate)


def slot(
    options: list[B],
    bought: set[int],
    limit: int = MAX_ALTERNATIVES,
    floor: int = MIN_FALLBACK_PLAYS,
) -> B | None:
    """Um degrau da lista de compra: as alternativas que se sustentam.

    Quatro regras, cada uma respondendo a um estrago já visto na tela:

    1. Passa quem `ranking` aprova — limite inferior de Wilson, piso de
       amostra e piso de frequência de escolha.
    2. Quando ninguém passa, o degrau repete a alternativa mais jogada
       — mas só se ela tiver `floor` partidas. É a única leitura que
       uma amostra fraca ainda sustenta; abaixo do piso não sobra
       leitura nenhuma, e o degrau some. Um buraco no meio da ordem de
       compra é ruim; um item de duas partidas com cara de
       recomendação é pior, porque o jogador não tem como saber que
       aquilo é ruído.
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
    alternativa — exceto consumível, que se recompra a cada volta e
    por isso nunca entra na reserva.

    `bought` é lido **e** atualizado; quem chama percorre os degraus na
    ordem de compra e o conjunto carrega o que já saiu.
    """
    if not options:
        return None
    chosen = list(ranking.ranked(options, sample))[:limit]
    if not chosen:
        popular = max(options, key=lambda block: block.games)
        if popular.games < floor:
            return None
        chosen = [popular]
    items: list[int] = []
    leader: B | None = None
    for block in chosen:
        taken_here = set(block.items)
        if taken_here & bought or taken_here & set(items):
            continue
        if leader is None:
            leader = block
            bought.update(set(block.items) - CONSUMABLES)
        items.extend(block.items)
    if leader is None:
        return None
    return replace(leader, items=tuple(items))


def extras(
    options: list[B],
    bought: set[int],
    label: str,
    limit: int = MAX_ALTERNATIVES,
    floor: int = MIN_FALLBACK_PLAYS,
) -> B | None:
    """Os itens mais construídos que a lista de compra ainda não cobriu.

    Existe porque o `last_items` do OP.GG **não é o último item**, por
    mais que o nome diga isso. É o ranking dos itens mais construídos
    do campeão inteiro, e a amostra prova: no Darius de Diamante+ o
    núcleo tem 1374 partidas e o `last_items` tem 22438 — um "último
    item" não pode ter dezesseis vezes mais partidas do que o começo da
    build. Tratado como degrau, ele mandava o Thresh fechar a build com
    o Trenó do Solstício (item de 22062 partidas que se compra cedo) e
    a Ahri com o Lacre Sombrio, de 350 de ouro.

    Aqui ele vira o que sempre foi: uma lista de itens que valem a pena
    e ainda não apareceram. Um item por alternativa — não a alternativa
    inteira — porque não há ordem de compra a comunicar, só opções.

    Itens de começo (`EARLY_ONLY`) não entram: o ranking de mais
    construídos é liderado por eles justamente porque todo mundo os
    compra, e nenhum deles é decisão de fim de partida.

    Devolve ``None`` quando tudo o que sobrou já está na build, que é o
    caso comum e saudável: significa que os degraus anteriores já
    escolheram os itens mais construídos do campeão.
    """
    if not options:
        return None
    ordered = list(ranking.ranked(options, sample))
    if not ordered:
        ordered = sorted(options, key=lambda block: block.games, reverse=True)
    items: list[int] = []
    leader: B | None = None
    for block in ordered:
        if block.games < floor:
            continue
        fresh = [
            item
            for item in block.items
            if item not in bought and item not in EARLY_ONLY
        ]
        if not fresh:
            continue
        if leader is None:
            leader = block
        items.append(fresh[0])
        bought.add(fresh[0])
        if len(items) >= limit:
            break
    if leader is None:
        return None
    return replace(leader, label=label, items=tuple(items))


def taken(blocks: Iterable) -> set[int]:
    """Tudo o que os blocos já mandaram comprar, pronto para `slot`."""
    return {item for block in blocks for item in block.items}
