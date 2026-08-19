from __future__ import annotations

import time
from typing import Callable

from ..config import Config, position_name
from ..lcu import endpoints
from ..lcu.client import LcuError


#: Intervalo entre tentativas de travar a mesma ação.
#: Uma trava aceita se reflete na sessão em muito menos que isso, então
#: em jogo normal nenhuma repetição chega a acontecer.
LOCK_RETRY_SECONDS = 1.0

#: Teto de PATCH de trava por ação, contando o primeiro. Sem teto, uma
#: ação que nunca fecha viraria enxurrada de requisição no cliente.
#: Com um envio por segundo, cobre quase toda uma fase de ban (~27s) —
#: insistir por poucos segundos não bastaria se o cliente só aceitar a
#: trava depois que a fase assenta.
MAX_LOCK_ATTEMPTS = 20


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


def local_position(session: dict) -> str:
    """Rota atribuída ao jogador local, ou vazio se o modo não atribui.

    É o único lugar que diz onde o jogador caiu de fato — vale tanto
    para a rota principal quanto para a secundária ou o autofill.
    """
    cell_id = session.get("localPlayerCellId")
    if cell_id is None:
        return ""
    for member in session.get("myTeam") or []:
        if member.get("cellId") == cell_id:
            position = member.get("assignedPosition")
            return position if isinstance(position, str) else ""
    return ""


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
        loadout=None,
    ) -> None:
        self._client = client
        self._config = config
        self._catalog = catalog
        self._log = log or (lambda message: None)
        self._now = now
        # Recebe a sessão de carona: o equipamento precisa exatamente do
        # que já foi buscado aqui, e um GET por tick a mais não se paga.
        self._loadout = loadout
        self._hovered_action: int | None = None
        self._hovered_at = 0.0
        self._warned_action: int | None = None
        self._locked_action: int | None = None
        self._locked_champion: int | None = None
        self._locked_at = 0.0
        self._lock_attempts = 0
        self._announced_position: str | None = None

    def reset(self) -> None:
        self._hovered_action = None
        self._hovered_at = 0.0
        self._warned_action = None
        self._locked_action = None
        self._locked_champion = None
        self._locked_at = 0.0
        self._lock_attempts = 0
        self._announced_position = None
        if self._loadout is not None:
            self._loadout.reset()

    def tick(self) -> None:
        session = self._client.get(endpoints.CHAMP_SELECT_SESSION)
        if not isinstance(session, dict):
            return
        if self._loadout is not None:
            self._loadout.apply(session)
        action = find_current_action(session)

        if self._locked_action is not None and (
            action is None or action["id"] != self._locked_action
        ):
            # A ação que travamos saiu de cena: agora dá para saber o que
            # o cliente gravou de fato.
            self._settle(session)

        if action is None:
            self._hovered_action = None
            return

        action_id = action["id"]
        if action_id == self._locked_action:
            # Por um instante depois do lock a sessão ainda devolve a ação
            # como em andamento. Sem lembrar o que já foi travado, o tick
            # seguinte refaria o hover do zero.
            self._retry_lock(action_id)
            return

        kind = action.get("type")
        taken = self._already_taken(session)
        if kind == "pick" and self._config.auto_pick:
            position = local_position(session)
            self._announce_position(position)
            available = self._available(endpoints.PICKABLE_CHAMPIONS)
            champion_id = next(
                (
                    c
                    for c in self._config.pick_list(position)
                    if c in available and c not in taken
                ),
                None,
            )
        elif kind == "ban" and self._config.auto_ban:
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

    def _announce_position(self, position: str) -> None:
        """Diz de que rota veio a lista, uma vez por seleção.

        Sem isso, cair de autofill numa rota sem lista própria parece
        defeito: o app escolheria pela lista geral sem explicar por quê.
        """
        if not position or position == self._announced_position:
            return
        self._announced_position = position
        name = position_name(position)
        if self._config.pick_priority_by_position.get(position.casefold()):
            self._log(f"Rota atribuída: {name} — usando a lista de {name}.")
        else:
            self._log(f"Rota atribuída: {name} — usando a lista geral.")

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
        self._lock_attempts = 0
        self._send_lock(action_id, champion_id)
        self._hovered_action = None

    def _retry_lock(self, action_id: int) -> None:
        """Reenvia a trava enquanto o cliente deixar a ação aberta.

        O PATCH responde 2xx mesmo quando não surte efeito — foi o que
        aconteceu numa ranqueada: o app anunciou o banimento e a sessão
        fechou a ação com -1. Se a ação continua aberta depois da trava,
        ela não pegou; insistir é o que resolve.
        """
        if self._locked_champion is None:
            return
        if self._lock_attempts >= MAX_LOCK_ATTEMPTS:
            return
        if self._now() - self._locked_at < LOCK_RETRY_SECONDS:
            return
        self._send_lock(action_id, self._locked_champion)

    def _send_lock(self, action_id: int, champion_id: int) -> None:
        self._client.patch(
            endpoints.CHAMP_SELECT_ACTION.format(action_id=action_id),
            json={"championId": champion_id, "completed": True},
        )
        self._locked_action = action_id
        self._locked_champion = champion_id
        self._locked_at = self._now()
        self._lock_attempts += 1

    def _settle(self, session: dict) -> None:
        """Relata o que o cliente gravou na ação que tentamos travar.

        Só aqui sai "confirmado": antes disso o app estava anunciando
        sucesso com base na resposta do PATCH, que mente.
        """
        action_id = self._locked_action
        champion_id = self._locked_champion
        self._locked_action = None
        self._locked_champion = None
        self._lock_attempts = 0
        if action_id is None or champion_id is None:
            return

        recorded = self._find_action(session, action_id)
        if recorded is None:
            # Sessão trocou de forma; sem base para afirmar nada.
            return

        actual = recorded.get("championId")
        if actual == champion_id:
            self._log(f"{self._catalog.name(champion_id)} confirmado.")
        elif isinstance(actual, int) and actual > 0:
            self._log(
                f"O cliente não registrou {self._catalog.name(champion_id)} "
                f"— ficou {self._catalog.name(actual)}."
            )
        else:
            self._log(
                f"O cliente não registrou {self._catalog.name(champion_id)} "
                "— a vez passou em branco."
            )

    @staticmethod
    def _find_action(session: dict, action_id: int) -> dict | None:
        for round_actions in session.get("actions") or []:
            for action in round_actions:
                if action.get("id") == action_id:
                    return action
        return None
