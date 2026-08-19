"""Quais filas o cliente aceita agora.

A lista de filas do app é fixa, mas a Riot liga e desliga fila por
região e por temporada. Quando isto foi escrito, Normal Blind (430),
Jogo Rápido (490) e Arena (1700) estavam desligadas nesta conta —
abrir lobby em qualquer uma delas responde 500 sem dizer por quê.

O cliente sabe disso o tempo todo, em `queueAvailability`. Perguntar
uma vez, ao conectar, evita o app oferecer uma fila que não existe.
"""

from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError

#: Único valor que quer dizer "pode jogar". Os outros vistos até agora
#: são "PlatformDisabled" e "DoesntMeetRequirements".
AVAILABLE = "Available"


def unavailable_queues(client) -> set[int]:
    """Ids que o cliente recusa agora.

    Devolve conjunto vazio quando a resposta falha ou vem com formato
    inesperado: sem informação, o certo é não tirar fila nenhuma do
    jogador — no pior caso ele vê o mesmo erro 500 de antes.
    """
    try:
        payload = client.get(endpoints.GAME_QUEUES)
    except ClientClosed:
        raise
    except LcuError:
        return set()
    if not isinstance(payload, list):
        return set()

    blocked = set()
    for queue in payload:
        if not isinstance(queue, dict):
            continue
        queue_id = queue.get("id")
        if not isinstance(queue_id, int) or isinstance(queue_id, bool):
            continue
        # Campo ausente conta como disponível: a falta do dado não é
        # motivo para bloquear uma fila que talvez funcione.
        availability = queue.get("queueAvailability")
        if availability is not None and availability != AVAILABLE:
            blocked.add(queue_id)
    return blocked
