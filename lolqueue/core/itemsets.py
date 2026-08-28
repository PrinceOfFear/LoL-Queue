"""O arsenal que aparece na loja, dentro da partida.

O cliente guarda todos os conjuntos de itens do jogador numa lista só, e
a única forma de mexer nela é reenviar a lista inteira. Não existe
"acrescentar um": existe substituir tudo. Quem usa Porofessor ou Blitz
tem dezenas de conjuntos ali, e uma gravação descuidada apaga o lote.

Daí a regra que organiza este módulo inteiro: **lê, junta, grava** — e
qualquer tropeço na leitura cancela a gravação. Do que está lá, só sai o
que tem o nosso nome; o resto é devolvido intacto, incluindo os campos
do envelope que não nos dizem respeito.

Diferente das runas, aqui não há reserva da Riot: sem dados do OP.GG,
nenhum conjunto é criado e a loja fica como estava.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from . import ranking
from .opgg import Block, Page

#: Como o conjunto se chama na loja — e como ele é reconhecido depois.
#: É a única marca que separa o nosso do que o usuário criou, então
#: mudá-la deixa órfão tudo que já foi gravado.
TITLE_PREFIX = "LoL Queue"

#: O bloco de recompra, igual em toda página. Não vem do OP.GG, e não
#: precisa vir: poção e sentinela não são recomendação estatística, são
#: o que se repõe a cada volta à base — por isso cabem aqui sem que nada
#: seja inventado. Os três totens ficam juntos de propósito; qual levar
#: depende da função, e mostrar os três é o contrário de escolher pelo
#: jogador.
CONSUMABLES_LABEL = "Consumíveis"
CONSUMABLES = (
    2003,  # Poção de Vida
    2055,  # Sentinela de Controle
    3340,  # Sentinela Invisível
    3363,  # Alteração Vidente
    3364,  # Lente do Oráculo
)

#: O Abismo Uivante, onde não se coloca sentinela — e onde a loja não
#: vende nenhuma das três. Só a Alteração Vidente existe lá, junto com a
#: poção. Conferido no campo `maps` do Data Dragon, patch 16.16.1: para
#: os ids 2055, 3340 e 3364 o mapa 12 vem desligado.
ARAM_MAP = 12
ARAM_CONSUMABLES = (2003, 3363)


def _items(items: Sequence[int]) -> list[dict]:
    """Os ids como o cliente quer: texto, e repetição virando contagem.

    Id numérico faz o cliente recusar a lista inteira, em silêncio. E
    duas poções ficam melhor como uma linha "x2" do que como duas
    linhas iguais na loja.
    """
    entries: list[dict] = []
    for item in items:
        if entries and entries[-1]["id"] == str(item):
            entries[-1]["count"] += 1
        else:
            entries.append({"count": 1, "id": str(item)})
    return entries


def _label(block: Block) -> str:
    """O rótulo do bloco: a taxa quando a amostra a sustenta, e o aviso quando não.

    Taxa sem amostra ao lado mente pelas duas pontas. "33% de vitórias"
    saiu de três partidas do Kog'Maw em Challenger, onde quase ninguém
    o joga — e leu-se como build ruim, quando o ruim era o tamanho da
    medição. `MIN_PLAYS` é o mesmo piso que `ranking` usa para eleger
    item: abaixo dele o número não é conselho, e dizer isso é mais útil
    do que exibi-lo.
    """
    if block.games and block.games < ranking.MIN_PLAYS:
        return f"{block.label} — amostra pequena ({block.games} partidas)"
    if not block.win_rate:
        return block.label
    if not block.games:
        return f"{block.label} — {round(block.win_rate * 100)}% de vitórias"
    return f"{block.label} — {round(block.win_rate * 100)}% em {block.games} partidas"


def _consumables(map_id: int) -> Block:
    """O bloco de recompra deste mapa.

    Mora aqui e não no OP.GG porque é o único ponto que sabe em que
    mapa a partida acontece — e porque não é dado do OP.GG.
    """
    items = ARAM_CONSUMABLES if map_id == ARAM_MAP else CONSUMABLES
    return Block(label=CONSUMABLES_LABEL, items=items, win_rate=0.0, games=0)


def item_set(
    champion_id: int,
    champion_name: str,
    blocks: Iterable[Block],
    map_id: int,
    page: int = 0,
    label: str = "",
) -> dict:
    """Monta o conjunto no formato que a LCU aceita.

    Amarrado ao campeão e ao mapa: sem isso o conjunto apareceria na
    loja de todo mundo, em toda partida. `page` distingue uma entre
    várias páginas de arsenal do mesmo campeão, e sustenta o `uid`.

    No título quem manda é `label`, o critério que montou a página:
    numerar as abas dizia quantas eram, não o que mudava dentro de cada
    uma. Sem rótulo o nome fica só o do campeão — é o caso de quando há
    uma página só, e também o de quem chama esta função direto.
    """
    if label:
        suffix = f" — {label}"
    else:
        suffix = "" if page == 0 else f" ({page + 1})"
    return {
        "associatedChampions": [champion_id],
        "associatedMaps": [map_id],
        "blocks": [
            {
                "hideIfSummonerSpell": "",
                "showIfSummonerSpell": "",
                "type": _label(block),
                "items": _items(block.items),
            }
            for block in (*blocks, _consumables(map_id))
        ],
        "map": "any",
        "mode": "any",
        "preferredItemSlots": [],
        "sortrank": 0,
        "startedFrom": "blank",
        "title": f"{TITLE_PREFIX}: {champion_name}{suffix}",
        "type": "custom",
        "uid": f"lolqueue-{champion_id}" if page == 0 else f"lolqueue-{champion_id}-{page}",
    }


class ItemSets:
    """Grava o arsenal do campeão sem encostar nos conjuntos alheios."""

    def __init__(self, client, log: Callable[[str], None] | None = None) -> None:
        self._client = client
        self._log = log or (lambda message: None)
        self._summoner_id: int | None = None

    def apply(
        self,
        champion_id: int,
        champion_name: str,
        pages: Iterable[Page],
        map_id: int,
    ) -> None:
        """Põe as páginas de arsenal deste campeão na loja.

        Cada página vira um conjunto de itens à parte, selecionável na
        loja como as abas do Porofessor ou do U.GG, e nomeado pelo
        critério que a montou. Erro nenhum sobe daqui — menos o cliente
        ter fechado, que não é falha de arsenal e sim o sinal de que o
        watcher precisa reconectar.
        """
        pages = tuple(page for page in pages if page.blocks)
        if not pages:
            return
        try:
            self._write(champion_id, champion_name, pages, map_id)
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não deu para montar o arsenal: {exc}")

    def _write(
        self,
        champion_id: int,
        champion_name: str,
        pages: Sequence[Page],
        map_id: int,
    ) -> None:
        path = self._path()
        if path is None:
            return
        payload = self._client.get(path)
        if not isinstance(payload, dict):
            return
        existing = payload.get("itemSets")
        if not isinstance(existing, list):
            # Formato inesperado. Gravar por cima seria apagar uma lista
            # que não conseguimos sequer ler.
            return

        mine = [
            item_set(
                champion_id,
                champion_name,
                page.blocks,
                map_id,
                page=index,
                label=page.label,
            )
            for index, page in enumerate(pages)
        ]
        body = dict(payload)
        body["itemSets"] = [
            item for item in existing if not self._is_ours(item)
        ] + mine
        self._client.put(path, json=body)
        if len(mine) == 1:
            self._log(f"Arsenal do OP.GG montado para {champion_name}.")
        else:
            self._log(
                f"Arsenal do OP.GG montado para {champion_name}, em "
                f"{len(mine)} páginas."
            )

    @staticmethod
    def _is_ours(item) -> bool:
        return isinstance(item, dict) and str(item.get("title", "")).startswith(
            f"{TITLE_PREFIX}:"
        )

    def _path(self) -> str | None:
        """A rota dos conjuntos, que depende do id do invocador."""
        if self._summoner_id is None:
            summoner = self._client.get(endpoints.CURRENT_SUMMONER)
            summoner_id = (
                summoner.get("summonerId") if isinstance(summoner, dict) else None
            )
            if not isinstance(summoner_id, int):
                return None
            self._summoner_id = summoner_id
        return endpoints.ITEM_SETS.format(summoner_id=self._summoner_id)
