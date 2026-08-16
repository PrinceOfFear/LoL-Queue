from __future__ import annotations

import time
from typing import Callable

from ..config import Config
from ..lcu import endpoints
from ..lcu.client import LcuError


def find_current_action(session: dict) -> dict | None:
    """Devolve a ação em andamento do jogador local, se houver.

    `actions` é uma lista de rodadas; cada rodada é uma lista de ações.
    Só interessa a nossa, em andamento e ainda não concluída.
    """
    cell_id = session.get("localPlayerCellId")
    if cell_id is None:
        return None
    for round_actions in session.get("actions") or []:
        for action in round_actions:
            if (
                action.get("actorCellId") == cell_id
                and action.get("isInProgress")
                and not action.get("completed")
            ):
                return action
    return None


class ChampSelectController:
    """Escolhe e bane campeões conforme a prioridade do usuário.

    Faz hover primeiro e trava depois do atraso configurado, dando ao
    usuário uma janela real para cancelar. O atraso é contado entre
    ticks; nada aqui bloqueia a thread.
    """

    def __init__(
        self,
        client,
        config: Config,
        catalog,
        log: Callable[[str], None] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._config = config
        self._catalog = catalog
        self._log = log or (lambda message: None)
        self._now = now
        self._hovered_action: int | None = None
        self._hovered_at = 0.0
        self._warned_action: int | None = None

    def reset(self) -> None:
        self._hovered_action = None
        self._hovered_at = 0.0
        self._warned_action = None

    def tick(self) -> None:
        session = self._client.get(endpoints.CHAMP_SELECT_SESSION)
        if not isinstance(session, dict):
            return
        action = find_current_action(session)
        if action is None:
            self._hovered_action = None
            return

        kind = action.get("type")
        if kind == "pick" and self._config.auto_pick:
            priority, available = self._config.pick_priority, self._available(
                endpoints.PICKABLE_CHAMPIONS
            )
        elif kind == "ban" and self._config.auto_ban:
            priority, available = self._config.ban_priority, self._available(
                endpoints.BANNABLE_CHAMPIONS
            )
        else:
            return

        champion_id = next((c for c in priority if c in available), None)
        action_id = action["id"]
        if champion_id is None:
            if self._warned_action != action_id:
                self._warned_action = action_id
                self._log(
                    f"Nenhum campeão da sua lista de {kind} está disponível. "
                    "Escolha manualmente."
                )
            return

        if self._hovered_action != action_id:
            self._hover(action_id, champion_id)
            return

        if self._now() - self._hovered_at >= self._config.lock_delay_seconds:
            self._lock(action_id, champion_id)

    def _available(self, path: str) -> set[int]:
        try:
            payload = self._client.get(path)
        except LcuError:
            return set()
        return set(payload) if isinstance(payload, list) else set()

    def _hover(self, action_id: int, champion_id: int) -> None:
        self._client.patch(
            endpoints.CHAMP_SELECT_ACTION.format(action_id=action_id),
            json={"championId": champion_id},
        )
        self._hovered_action = action_id
        self._hovered_at = self._now()
        delay = self._config.lock_delay_seconds
        self._log(
            f"Selecionando {self._catalog.name(champion_id)} "
            f"— travando em {delay:.0f}s."
        )

    def _lock(self, action_id: int, champion_id: int) -> None:
        self._client.patch(
            endpoints.CHAMP_SELECT_ACTION.format(action_id=action_id),
            json={"championId": champion_id, "completed": True},
        )
        self._log(f"{self._catalog.name(champion_id)} confirmado.")
        self._hovered_action = None
