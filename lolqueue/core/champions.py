from __future__ import annotations

import time

from ..lcu import endpoints
from ..lcu.client import LcuError

#: Tentativas de `load_with_retries` e a pausa entre elas. Cobre a corrida
#: comum de reconexão: o lockfile aparece e a API já responde, mas os
#: dados estáticos (a lista de campeões entre eles) levam mais um
#: instante para ficar prontos.
CATALOG_LOAD_ATTEMPTS = 5
CATALOG_LOAD_RETRY_DELAY = 0.4


class ChampionCatalog:
    """Nomes e ids dos campeões, vindos do próprio cliente.

    A carga é preguiçosa e tolerante: se a API falhar, o catálogo
    continua utilizável — `name()` cai no id numérico e a UI segue de pé.
    """

    def __init__(self, client) -> None:
        self._client = client
        self._by_id: dict[int, str] = {}
        self._by_alias: dict[int, str] = {}
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
        by_alias: dict[int, str] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            champion_id = entry.get("id")
            name = entry.get("name")
            alias = entry.get("alias")
            if not isinstance(champion_id, int) or champion_id <= 0:
                continue  # o cliente devolve um sentinela id=-1 "Nenhum"
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(alias, str) or "_" in alias:
                # Variantes de outros modos vêm como `Jade_MasterYi`: mesmo
                # nome do original, id inválido para a seleção normal. O
                # alias de um campeão de verdade nunca tem underscore, e o
                # clone vem depois na lista — sem cortar aqui, ele ainda
                # roubaria a busca por nome do original.
                continue
            by_id[champion_id] = name
            by_name[name.casefold()] = champion_id
            by_alias[champion_id] = alias

        self._by_id = by_id
        self._by_name = by_name
        self._by_alias = by_alias
        self._loaded = True

    def load_with_retries(
        self,
        attempts: int = CATALOG_LOAD_ATTEMPTS,
        delay: float = CATALOG_LOAD_RETRY_DELAY,
    ) -> None:
        """Dá ao catálogo algumas chances antes de aceitar a falha.

        `load()` sozinho tenta uma vez e, se falhar, o catálogo fica vazio
        para sempre — nada mais o chama de novo. Reconectar bem no instante
        em que o cliente do LoL termina de subir cai exatamente nessa
        corrida: a API já aceita chamadas, mas `CHAMPION_SUMMARY` ainda
        responde erro por um instante. Sem repetir aqui, só fechar e
        reabrir o app dava tempo suficiente para o cliente terminar de
        subir — o que essa função agora faz sozinha, dentro da mesma
        conexão. Se a falha for de verdade (não só o instante da corrida),
        desiste após `attempts` tentativas e segue tolerante: o resto do
        app já sabe lidar com o catálogo vazio.
        """
        for attempt in range(attempts):
            self.load()
            if self._loaded or attempt == attempts - 1:
                return
            time.sleep(delay)

    def name(self, champion_id: int) -> str:
        return self._by_id.get(champion_id, f"#{champion_id}")

    def alias(self, champion_id: int) -> str:
        """Identificador da Riot, igual em qualquer idioma.

        O nome de exibição vem traduzido pelo cliente. Para falar com
        gente de fora — um site de estatísticas, por exemplo — é o
        alias que serve.
        """
        return self._by_alias.get(champion_id, "")

    def knows(self, champion_id: int) -> bool:
        """Se o campeão existe mesmo. Falso enquanto o catálogo não veio."""
        return champion_id in self._by_id

    def id_for(self, name: str) -> int | None:
        return self._by_name.get(name.casefold())

    def all(self) -> list[tuple[int, str]]:
        return sorted(self._by_id.items(), key=lambda item: item[1])
