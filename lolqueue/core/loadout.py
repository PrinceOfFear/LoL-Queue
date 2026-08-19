"""Feitiços e runas a partir da recomendação da Riot.

O cliente já sabe o que é bom para cada campeão em cada rota — é o que
ele mostra na seleção de campeões, e sai por
`/lol-perks/v1/recommended-pages`. Uma chamada devolve as runas e os
feitiços de uma vez, então não há nada para o usuário configurar aqui
além de ligar ou desligar.

O que este módulo cuida de não estragar:

- **o lado do Flash.** A recomendação vem numa ordem qualquer, e trocar
  a tecla do Flash minutos antes da partida custa mais do que qualquer
  runa devolve.
- **as páginas de runas do usuário.** O app mantém uma página só, a
  dele, reconhecida pelo nome. Sem espaço para criá-la, ele desiste e
  avisa; apagar página alheia para abrir vaga está fora de questão.

Erros aqui não sobem: se a recomendação falhar, a seleção e o
banimento automáticos seguem sem saber de nada.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from ..config import Config
from ..lcu import endpoints
from ..lcu.client import LcuError

#: Prefixo do nome da página que o app cria. É por ele que a página é
#: reconhecida depois — e é o que separa a nossa das do usuário.
PAGE_PREFIX = "LoL Queue"

#: Mapa padrão quando o cliente não diz qual é: a Fenda.
DEFAULT_MAP = 11


def align_spells(
    recommended: Sequence[int], current: Iterable[int | None]
) -> tuple[int, int]:
    """Põe a dupla recomendada na ordem que o jogador já usa.

    Se algum feitiço aparece nos dois pares em lados trocados, a dupla
    inteira é invertida. Na prática isso é o Flash: quem o tem no D
    continua com ele no D. Como só existem dois lados, um feitiço em
    comum já decide a ordem dos dois.
    """
    first, second = recommended[0], recommended[1]
    mine = list(current)
    if first in mine[1:] or second in mine[:1]:
        return second, first
    return first, second


def local_champion(session: dict) -> int:
    """Campeão travado pelo jogador local, ou 0 enquanto não houver.

    Fica em zero durante o hover: o cliente só preenche `championId`
    depois da trava. É de propósito que o equipamento espere por isso —
    aplicar runa em campeão que ainda pode mudar seria trabalho jogado
    fora, e visível para o usuário.
    """
    cell_id = session.get("localPlayerCellId")
    for member in session.get("myTeam") or []:
        if member.get("cellId") == cell_id:
            champion_id = member.get("championId")
            return champion_id if isinstance(champion_id, int) else 0
    return 0


def local_spells(session: dict) -> tuple[int | None, int | None]:
    """Feitiços que o jogador local tem escolhidos agora."""
    cell_id = session.get("localPlayerCellId")
    for member in session.get("myTeam") or []:
        if member.get("cellId") == cell_id:
            return member.get("spell1Id"), member.get("spell2Id")
    return None, None


class Loadout:
    """Aplica feitiços e runas quando o campeão fica definido."""

    def __init__(
        self,
        client,
        config: Config,
        catalog,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._catalog = catalog
        self._log = log or (lambda message: None)
        self._done_for: int | None = None

    def reset(self) -> None:
        self._done_for = None

    def apply(self, session: dict) -> None:
        if not (self._config.auto_spells or self._config.auto_runes):
            return
        champion_id = local_champion(session)
        if champion_id <= 0 or champion_id == self._done_for:
            return

        # Marcado antes de agir: uma falha no meio do caminho não pode
        # virar uma tentativa por tick pelo resto da seleção.
        self._done_for = champion_id
        try:
            recommendation = self._recommendation(champion_id, session)
            if recommendation is None:
                return
            if self._config.auto_spells:
                self._apply_spells(recommendation, session)
            if self._config.auto_runes:
                self._apply_runes(recommendation, champion_id)
        except LcuError as exc:
            self._log(f"Não deu para aplicar runas e feitiços: {exc}")

    # ---------- recomendação ----------

    def _recommendation(self, champion_id: int, session: dict) -> dict | None:
        from .champ_select import local_position

        position = local_position(session).upper() or "NONE"
        payload = self._client.get(
            endpoints.PERK_RECOMMENDED.format(
                champion_id=champion_id,
                position=position,
                map_id=self._map_id(),
            )
        )
        if not isinstance(payload, list) or not payload:
            self._log(
                f"A Riot não recomendou nada para {self._catalog.name(champion_id)}."
            )
            return None
        return payload[0]

    def _map_id(self) -> int:
        """Fenda ou Abismo. A recomendação muda entre os dois."""
        session = self._client.get(endpoints.GAMEFLOW_SESSION)
        if isinstance(session, dict):
            map_id = (session.get("map") or {}).get("id")
            if isinstance(map_id, int):
                return map_id
        return DEFAULT_MAP

    # ---------- feitiços ----------

    def _apply_spells(self, recommendation: dict, session: dict) -> None:
        spells = recommendation.get("summonerSpellIds")
        if not isinstance(spells, list) or len(spells) < 2:
            return
        current = local_spells(session)
        first, second = align_spells(spells, current)
        if (first, second) == current:
            return
        self._client.patch(
            endpoints.CHAMP_SELECT_MY_SELECTION,
            json={"spell1Id": first, "spell2Id": second},
        )
        self._log("Feitiços recomendados aplicados.")

    # ---------- runas ----------

    def _apply_runes(self, recommendation: dict, champion_id: int) -> None:
        name = f"{PAGE_PREFIX}: {self._catalog.name(champion_id)}"
        self._discard_old_pages()
        if not self._has_room():
            self._log(
                "Sem espaço para uma página de runas — apague uma das suas "
                "ou desligue as runas automáticas."
            )
            return

        page = self._client.post(
            endpoints.PERK_PAGES,
            json={
                "name": name,
                "primaryStyleId": recommendation.get("primaryPerkStyleId"),
                "subStyleId": recommendation.get("secondaryPerkStyleId"),
                "selectedPerkIds": [
                    perk.get("id") for perk in recommendation.get("perks") or []
                ],
            },
        )
        page_id = page.get("id") if isinstance(page, dict) else None
        if page_id is None:
            self._log("O cliente não devolveu a página de runas criada.")
            return
        # Criar não ativa: sem este passo o jogador entraria na partida
        # com a página que estava selecionada antes.
        self._client.put(endpoints.PERK_CURRENT_PAGE, json=page_id)
        self._log(f"Runas recomendadas aplicadas — página “{name}”.")

    def _discard_old_pages(self) -> None:
        """Apaga a página que o app criou antes, e só ela."""
        pages = self._client.get(endpoints.PERK_PAGES)
        if not isinstance(pages, list):
            return
        for page in pages:
            name = page.get("name")
            if not isinstance(name, str) or not name.startswith(PAGE_PREFIX):
                continue
            if not page.get("isDeletable", True):
                continue
            self._client.delete(endpoints.PERK_PAGE.format(page_id=page["id"]))

    def _has_room(self) -> bool:
        inventory = self._client.get(endpoints.PERK_INVENTORY)
        if not isinstance(inventory, dict):
            return True
        return bool(inventory.get("canAddCustomPage", True))
