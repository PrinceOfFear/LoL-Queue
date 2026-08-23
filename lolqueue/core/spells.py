"""O catálogo de feitiços de invocador do patch atual, pelo cliente do LoL.

Mesmo desenho de `core/items.py`: o histórico de partidas só manda o
id de cada feitiço, e o ícone para desenhar vem daqui.
"""

from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import LcuError


class SpellCatalog:
    """Ícone de cada feitiço de invocador, por id."""

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
            spells = self._client.get(endpoints.SUMMONER_SPELLS)
        except LcuError:
            return
        if not isinstance(spells, list):
            return
        found: dict[int, str] = {}
        for entry in spells:
            if not isinstance(entry, dict):
                continue
            spell_id = entry.get("id")
            if not isinstance(spell_id, int):
                continue
            found[spell_id] = str(entry.get("iconPath") or "")
        if not found:
            return
        self._icons = found
        self._loaded = True

    def icon_path(self, spell_id: int) -> str:
        return self._icons.get(spell_id, "")

    def icons(self) -> list[str]:
        return sorted({path for path in self._icons.values() if path})
