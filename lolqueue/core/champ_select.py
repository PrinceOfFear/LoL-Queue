from __future__ import annotations

import random
import time
from typing import Callable

from ..config import Config, position_name
from ..lcu import endpoints
from ..lcu.client import LcuError
from .delay import Rng, sample


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

#: O "Nenhum" da grade de ban. Fechar a ação com ele é o que o cliente
#: entende por passar a vez de propósito — diferente de deixar o tempo
#: acabar, que fica gravado como -1.
NO_CHAMPION = 0


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


def find_pick_action(session: dict) -> dict | None:
    """Devolve a nossa vez de escolher, mesmo que ainda não tenha chegado.

    Diferente de `find_current_action`: aqui não importa se a ação está
    em andamento, só que seja nossa, do tipo pick e ainda aberta. É essa
    ação que o cliente usa para mostrar o retrato sobre o nosso quadro
    durante a fase de banimento — a "intenção" que o time vê.
    """
    cell_id = session.get("localPlayerCellId")
    if cell_id is None:
        return None
    for round_actions in session.get("actions") or []:
        for action in round_actions:
            if (
                action.get("actorCellId") == cell_id
                and action.get("type") == "pick"
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
        antitoxic=None,
        rng: Rng = random.uniform,
        on_pick_predicted: Callable[[int | None], None] | None = None,
        on_position: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._catalog = catalog
        self._log = log or (lambda message: None)
        self._now = now
        self._rng = rng
        # Recebe a sessão de carona: o equipamento precisa exatamente do
        # que já foi buscado aqui, e um GET por tick a mais não se paga.
        self._loadout = loadout
        # Silencia chat e emotes nas opções do jogo enquanto a seleção
        # corre — é a última janela antes de a partida abrir.
        self._antitoxic = antitoxic
        # Quando esta seleção apareceu. É daqui que sai a espera antes
        # de declarar a intenção.
        self._session_seen_at: float | None = None
        self._hovered_action: int | None = None
        self._hovered_at = 0.0
        # Quanto esperar entre mostrar e travar. Sorteado por ação, para
        # que duas partidas não tenham o mesmo compasso.
        self._lock_after = 0.0
        self._warned_action: int | None = None
        self._locked_action: int | None = None
        self._locked_champion: int | None = None
        self._locked_at = 0.0
        self._lock_attempts = 0
        # Vez de banir que já tentamos passar em branco, para não
        # reabrir a tentativa a cada tick se o cliente recusar.
        self._passed_action: int | None = None
        self._announced_position: str | None = None
        # Avisa a UI qual campeão a lista escolheria agora — não depende
        # de ser a nossa vez, é a prévia de "assim que a partida abrir".
        self._on_pick_predicted = on_pick_predicted
        self._predicted: int | None = None
        # Avisa a UI em que rota o cliente nos colocou — é o que diz
        # qual das listas de prioridade está valendo agora, e portanto
        # qual delas a Central deixa reordenar.
        self._on_position = on_position
        self._position = ""
        # Quem é "pickável" não muda durante a seleção; perguntar de novo
        # a cada tick só para a prévia seria puxar o cliente à toa.
        self._pickable_cache: set[int] = set()
        # A intenção já mostrada no cliente: (ação, campeão). Sem
        # lembrar disso, todo tick reenviaria o mesmo PATCH e a tela de
        # seleção piscaria o retrato sem parar.
        self._intent_action: int | None = None
        self._intent_champion: int | None = None
        # Vira True assim que a vez de escolher de verdade começa. Sem
        # isto, travar o pick real marca o campeão como "já tirado" na
        # sessão e o próximo tick empurraria a prévia pro segundo da
        # lista — bem na hora em que o pick de verdade acabou de sair.
        self._prediction_settled = False

    def reset(self) -> None:
        self._hovered_action = None
        self._hovered_at = 0.0
        self._lock_after = 0.0
        self._warned_action = None
        self._locked_action = None
        self._locked_champion = None
        self._locked_at = 0.0
        self._lock_attempts = 0
        self._passed_action = None
        self._announced_position = None
        self._pickable_cache = set()
        self._prediction_settled = False
        self._intent_action = None
        self._intent_champion = None
        self._session_seen_at = None
        self._report_position("")
        if self._predicted is not None:
            self._predicted = None
            if self._on_pick_predicted is not None:
                self._on_pick_predicted(None)
        if self._loadout is not None:
            self._loadout.reset()
        if self._antitoxic is not None:
            self._antitoxic.reset()

    def tick(self) -> None:
        session = self._client.get(endpoints.CHAMP_SELECT_SESSION)
        if not isinstance(session, dict):
            return
        if self._session_seen_at is None:
            self._session_seen_at = self._now()
        if self._antitoxic is not None:
            self._antitoxic.apply()
        if self._loadout is not None:
            self._loadout.apply(session)
        self._report_position(local_position(session))
        self._update_prediction(session)
        self._declare_intent(session)
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
            # A partir daqui a prévia para de recalcular sozinha: é a
            # nossa vez de verdade, e este cálculo (fresco, não o do
            # cache de `_pickable()`) é quem manda — mesmo quando não
            # sobrou candidato nenhum.
            self._settle_prediction(champion_id)
        elif kind == "ban" and self._config.auto_ban:
            if not self._config.ban_priority:
                if self._passed_action == action_id:
                    return
                # Banir marcado com a lista vazia não é descuido: é o
                # "Nenhum" da grade. Quem escolheu campeões e ficou sem
                # opção cai no aviso logo abaixo, como antes.
                champion_id = NO_CHAMPION
            else:
                champion_id = next(
                    (c for c in self._config.ban_priority if c not in taken),
                    None,
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

        if champion_id == NO_CHAMPION:
            self._pass_turn(action_id)
            return

        if self._hovered_action != action_id:
            self._hover(action_id, champion_id, kind)
            return

        if self._now() - self._hovered_at >= self._lock_after:
            self._lock(action_id, champion_id)

    def _report_position(self, position: str) -> None:
        """Publica a rota atribuída, só quando ela muda.

        Separado de `_announce_position`, que escreve no registro uma
        vez por seleção: este aqui é estado de tela, e precisa voltar a
        vazio no `reset()` para a Central não ficar mostrando a lista da
        rota da partida passada.
        """
        if position == self._position:
            return
        self._position = position
        if self._on_position is not None:
            self._on_position(position)

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

    def _pickable(self) -> set[int]:
        """`PICKABLE_CHAMPIONS`, buscado uma vez por seleção.

        A trava de verdade sempre pergunta na hora — aqui vale menos
        precisão: é só a prévia. Só não fixa um resultado vazio no
        cache, porque a lista pode não ter povoado ainda bem no início
        da seleção; sem isso a prévia ficaria presa em "nada" até o
        próximo `reset()`.
        """
        if not self._pickable_cache:
            self._pickable_cache = self._available(endpoints.PICKABLE_CHAMPIONS)
        return self._pickable_cache

    def _update_prediction(self, session: dict) -> None:
        """Recalcula o próximo pick provável e avisa só quando muda.

        Roda a cada tick da seleção inteira, não só na vez de escolher:
        é a prévia que a UI mostra assim que a partida é aceita, bem
        antes da ação de pick existir.
        """
        if self._on_pick_predicted is None or not self._config.auto_pick:
            return
        if self._prediction_settled:
            return
        position = local_position(session)
        taken = self._already_taken(session)
        # Lista vazia aqui é "ainda não sei", não "nenhum campeão vale".
        # Medido numa seleção real: durante o `BAN_PICK` a rota já
        # responde com a lista inteira (173 campeões), então o caso comum
        # não é esse — o que sobra é a rota falhar, e aí `_available`
        # devolve conjunto vazio. Tratar isso como "nenhum vale" apagaria
        # a prévia justo no trecho em que ela mais serve. Sem lista, vale
        # a intenção da prioridade: quem confere de verdade é a trava,
        # que pergunta na hora, e `_settle_prediction` corrige a tela se
        # o real divergir.
        pickable = self._pickable()
        predicted = next(
            (
                c
                for c in self._config.pick_list(position)
                if c not in taken and (not pickable or c in pickable)
            ),
            None,
        )
        if predicted != self._predicted:
            self._predicted = predicted
            self._on_pick_predicted(predicted)

    def _settle_prediction(self, champion_id: int | None) -> None:
        """Trava a prévia no que o pick real de fato vai usar.

        Chamado uma vez por tick a partir do momento em que é a nossa
        vez de escolher — depois disso `_update_prediction` para de
        recalcular. `champion_id` vem do cálculo fresco desse bloco
        (via `_available`, não do `_pickable_cache`), então é a fonte
        de verdade: se ele for diferente do que a prévia (baseada no
        cache) tinha mostrado até aqui — inclusive `None`, quando não
        sobrou candidato — a UI precisa saber.
        """
        self._prediction_settled = True
        if self._on_pick_predicted is None:
            return
        if champion_id != self._predicted:
            self._predicted = champion_id
            self._on_pick_predicted(champion_id)

    def _intent_due(self) -> bool:
        """Se já dá para mostrar o retrato no cliente.

        A sessão existe na API antes de a tela de seleção terminar de
        carregar. Declarar nesse instante entrega o pick ao time inteiro
        antes de o próprio jogador ver a tela — e quem quiser atrapalhar
        ainda tem a seleção toda pela frente. A espera cabe aqui, e não
        no envio, para que uma recusa do cliente continue sendo tratada
        como sempre foi.
        """
        if self._session_seen_at is None:
            return False
        espera = self._config.pick_intent_delay
        return self._now() - self._session_seen_at >= espera

    def _declare_intent(self, session: dict) -> None:
        """Mostra no cliente do LoL quem a lista vai escolher.

        É o mesmo gesto de clicar num campeão antes da sua vez: o
        retrato aparece sobre o seu quadro na tela de seleção, para você
        e para o time, sem travar nada. Serve para o time se organizar
        enquanto os banimentos correm — a prévia dentro do app só quem
        está de olho nele vê.

        Não age depois que a vez chega: dali em diante quem manda no
        retrato é o par hover/trava, que patcha esta mesma ação e conta
        o tempo do atraso configurado. Recusa do cliente não é tratada
        como erro — o retrato é enfeite, e a escolha de verdade pergunta
        tudo de novo na hora.
        """
        if not self._config.show_pick_intent or not self._config.auto_pick:
            return
        if not self._intent_due():
            return
        champion_id = self._predicted
        if champion_id is None:
            return
        action = find_pick_action(session)
        if action is None or action.get("isInProgress"):
            return
        action_id = action.get("id")
        if action_id is None:
            return
        if (action_id, champion_id) == (self._intent_action, self._intent_champion):
            return
        # Lembra antes de enviar: falhando ou não, este par já foi
        # tentado, e insistir a cada tick só encheria o cliente.
        self._intent_action = action_id
        self._intent_champion = champion_id
        if action.get("championId") == champion_id:
            # O cliente já mostra este campeão — nada a corrigir.
            return
        try:
            self._client.patch(
                endpoints.CHAMP_SELECT_ACTION.format(action_id=action_id),
                json={"championId": champion_id},
            )
        except LcuError:
            return
        self._log(
            f"Mostrando {self._catalog.name(champion_id)} no cliente "
            "— ainda dá para mudar a ordem."
        )

    def _hover(self, action_id: int, champion_id: int, kind: str) -> None:
        self._client.patch(
            endpoints.CHAMP_SELECT_ACTION.format(action_id=action_id),
            json={"championId": champion_id},
        )
        self._hovered_action = action_id
        self._hovered_at = self._now()
        # O sorteio é aqui, e não na leitura da config, para que a
        # mensagem anuncie exatamente o tempo que vai ser esperado.
        self._lock_after = sample(
            self._config.lock_delay_min, self._config.lock_delay_max, self._rng
        )
        delay = self._lock_after
        verbo = "Banindo" if kind == "ban" else "Selecionando"
        self._log(
            f"{verbo} {self._catalog.name(champion_id)} "
            f"— travando em {delay:.0f}s."
        )

    def _lock(self, action_id: int, champion_id: int) -> None:
        self._lock_attempts = 0
        self._send_lock(action_id, champion_id)
        self._hovered_action = None

    def _pass_turn(self, action_id: int) -> None:
        """Anuncia a vez em branco uma vez e só observa o resultado.

        Não existe operação da LCU que feche essa vez mais cedo: um
        PATCH com championId 0 responde 2xx, mas o cliente nunca fecha
        a ação com ele — só o relógio da própria fase de ban faz isso,
        de 15 a 40s depois, medido em partida real. Insistir só enche o
        cliente de requisição atoa; o app avisa e espera quieto, e
        `_settle` relata o que de fato aconteceu quando a vez passar.
        """
        if self._passed_action == action_id:
            return
        self._passed_action = action_id
        self._hovered_action = None
        self._locked_action = action_id
        self._locked_champion = NO_CHAMPION
        self._log("Sem campeão na sua lista de ban — deixando a vez passar.")

    def _retry_lock(self, action_id: int) -> None:
        """Reenvia a trava enquanto o cliente deixar a ação aberta.

        O PATCH responde 2xx mesmo quando não surte efeito — foi o que
        aconteceu numa ranqueada: o app anunciou o banimento e a sessão
        fechou a ação com -1. Se a ação continua aberta depois da trava,
        ela não pegou; insistir é o que resolve.
        """
        if self._locked_champion in (None, NO_CHAMPION):
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
        if champion_id == NO_CHAMPION:
            # Vez passada de propósito: o cliente grava 0 ou -1, e
            # qualquer um dos dois é o resultado que foi pedido.
            if isinstance(actual, int) and actual > 0:
                self._log(
                    "A vez de banir não ficou em branco "
                    f"— saiu {self._catalog.name(actual)}."
                )
            else:
                self._log("Vez de banir passada em branco.")
            return
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
