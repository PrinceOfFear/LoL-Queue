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
from ..lcu.client import LcuError
from .opgg import Block

#: Como o conjunto se chama na loja — e como ele é reconhecido depois.
#: É a única marca que separa o nosso do que o usuário criou, então
#: mudá-la deixa órfão tudo que já foi gravado.
TITLE_PREFIX = "LoL Queue"


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
    """O rótulo do bloco, com a taxa de vitória quando ela é conhecida."""
    if not block.win_rate:
        return block.label
    return f"{block.label} — {round(block.win_rate * 100)}% de vitórias"


def item_set(
    champion_id: int, champion_name: str, blocks: Iterable[Block], map_id: int
) -> dict:
    """Monta o conjunto no formato que a LCU aceita.

    Amarrado ao campeão e ao mapa: sem isso o conjunto apareceria na
    loja de todo mundo, em toda partida.
    """
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
            for block in blocks
        ],
        "map": "any",
        "mode": "any",
        "preferredItemSlots": [],
        "sortrank": 0,
        "startedFrom": "blank",
        "title": f"{TITLE_PREFIX}: {champion_name}",
        "type": "custom",
        "uid": f"lolqueue-{champion_id}",
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
        blocks: Iterable[Block],
        map_id: int,
    ) -> None:
        """Põe o arsenal deste campeão na loja. Erro nenhum sobe daqui."""
        blocks = tuple(blocks)
        if not blocks:
            return
        try:
            self._write(champion_id, champion_name, blocks, map_id)
        except LcuError as exc:
            self._log(f"Não deu para montar o arsenal: {exc}")

    def _write(
        self,
        champion_id: int,
        champion_name: str,
        blocks: Sequence[Block],
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

        mine = item_set(champion_id, champion_name, blocks, map_id)
        body = dict(payload)
        body["itemSets"] = [
            item for item in existing if not self._is_ours(item)
        ] + [mine]
        self._client.put(path, json=body)
        self._log(f"Arsenal do OP.GG montado para {champion_name}.")

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
