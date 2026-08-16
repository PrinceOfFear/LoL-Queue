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
        self._locked_action: int | None = None

    def reset(self) -> None:
        self._hovered_action = None
        self._hovered_at = 0.0
        self._warned_action = None
        self._locked_action = None

    def tick(self) -> None:
        session = self._client.get(endpoints.CHAMP_SELECT_SESSION)
        if not isinstance(session, dict):
            return
        action = find_current_action(session)
        if action is None:
            self._hovered_action = None
            return

        action_id = action["id"]
        if action_id == self._locked_action:
            # Por um instante depois do lock a sessão ainda devolve a ação
            # como em andamento. Sem lembrar o que já foi travado, o tick
            # seguinte refaria o hover do zero.
            return

        kind = action.get("type")
        if kind == "pick" and self._config.auto_pick:
            available = self._available(endpoints.PICKABLE_CHAMPIONS)
            champion_id = next(
                (c for c in self._config.pick_priority if c in available), None
            )
        elif kind == "ban" and self._config.auto_ban:
            taken = self._already_taken(session)
            champion_id = next(
                (c for c in self._config.ban_priority if c not in taken), None
            )
        else:
            return

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

    @staticmethod
    def _already_taken(session: dict) -> set[int]:
        """Campeões fora de jogo: já banidos ou já escolhidos.

        Para banir não dá para usar `bannable-champion-ids`: o cliente
        responde só `[-1]`, um sentinela, e filtrar por ele zerava a
        lista inteira. Vale banir qualquer campeão que ninguém tenha
        tirado de jogo ainda, e isso está na própria sessão.

        Uma vez de banir que expirou fica gravada com `championId` -1;
        o corte em zero descarta esse caso.
        """
        taken: set[int] = set()
        for round_actions in session.get("actions") or []:
            for action in round_actions:
                if not action.get("completed"):
                    continue
                if action.get("type") not in ("ban", "pick"):
                    continue
                champion_id = action.get("championId")
                if isinstance(champion_id, int) and champion_id > 0:
                    taken.add(champion_id)
        return taken

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
        self._locked_action = action_id
