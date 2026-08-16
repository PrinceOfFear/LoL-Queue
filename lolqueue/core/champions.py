from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import LcuError


class ChampionCatalog:
    """Nomes e ids dos campeões, vindos do próprio cliente.

    A carga é preguiçosa e tolerante: se a API falhar, o catálogo
    continua utilizável — `name()` cai no id numérico e a UI segue de pé.
    """

    def __init__(self, client) -> None:
        self._client = client
        self._by_id: dict[int, str] = {}
        self._by_name: dict[str, int] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Carrega o catálogo uma única vez. Erros são engolidos de propósito."""
        if self._loaded:
            return
        try:
            data = self._client.get(endpoints.CHAMPION_SUMMARY)
        except LcuError:
            return
        if not isinstance(data, list):
            return

        by_id: dict[int, str] = {}
        by_name: dict[str, int] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            champion_id = entry.get("id")
            name = entry.get("name")
            if not isinstance(champion_id, int) or champion_id <= 0:
                continue  # o cliente devolve um sentinela id=-1 "Nenhum"
            if not isinstance(name, str) or not name:
                continue
            by_id[champion_id] = name
            by_name[name.casefold()] = champion_id

        self._by_id = by_id
        self._by_name = by_name
        self._loaded = True

    def name(self, champion_id: int) -> str:
        return self._by_id.get(champion_id, f"#{champion_id}")

    def id_for(self, name: str) -> int | None:
        return self._by_name.get(name.casefold())

    def all(self) -> list[tuple[int, str]]:
        return sorted(self._by_id.items(), key=lambda item: item[1])
