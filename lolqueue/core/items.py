"""O catálogo de itens do patch atual, pelo próprio cliente do LoL.

O histórico de partidas do OP.GG só manda o id de cada item; o ícone
para desenhar a grade da linha vem daqui, do mesmo jeito que
`core/perks.py` traz o das runas. Sem nome aqui: a UI já recebe
`items_names` pronto do próprio OP.GG.
"""

from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import LcuError


class ItemCatalog:
    """Ícone de cada item, por id — carga preguiçosa e tolerante a falha."""

    def __init__(self, client) -> None:
        self._client = client
        self._icons: dict[int, str] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        if self._loaded:
            return
        try:
            items = self._client.get(endpoints.ITEMS)
        except LcuError:
            return
        if not isinstance(items, list):
            return
        found: dict[int, str] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("id")
            if not isinstance(item_id, int):
                continue
            found[item_id] = str(entry.get("iconPath") or "")
        if not found:
            return
        self._icons = found
        self._loaded = True

    def icon_path(self, item_id: int) -> str:
        """O `iconPath` cru do item, ou vazio se não conhecido."""
        return self._icons.get(item_id, "")

    def icons(self) -> list[str]:
        """Todo caminho de imagem que o catálogo conhece, sem repetir."""
        return sorted({path for path in self._icons.values() if path})
