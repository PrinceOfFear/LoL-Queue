"""Filas que a Riot desligou.

O seletor lista sete filas fixas, mas a Riot liga e desliga fila por
região e por temporada: Normal Blind, Jogo Rápido e Arena estavam
desligadas quando isto foi escrito, e criar lobby numa delas responde
500. Escolher uma fila que não existe e só descobrir isso quando o
motor falha é ruim demais para deixar passar.
"""

from lolqueue.core.queues import unavailable_queues
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

QUEUES = [
    {"id": 420, "queueAvailability": "Available"},
    {"id": 430, "queueAvailability": "PlatformDisabled"},
    {"id": 490, "queueAvailability": "PlatformDisabled"},
    {"id": 450, "queueAvailability": "Available"},
]


def test_it_lists_the_queues_the_client_refuses():
    client = FakeLcuClient({endpoints.GAME_QUEUES: QUEUES})

    assert unavailable_queues(client) == {430, 490}


def test_a_failure_leaves_every_queue_usable():
    """Sem resposta, o certo é não atrapalhar quem quer jogar."""
    client = FakeLcuClient(failures={endpoints.GAME_QUEUES})

    assert unavailable_queues(client) == set()


def test_an_unexpected_shape_leaves_every_queue_usable():
    client = FakeLcuClient({endpoints.GAME_QUEUES: {"erro": "nada"}})

    assert unavailable_queues(client) == set()


def test_a_queue_without_the_field_counts_as_usable():
    client = FakeLcuClient({endpoints.GAME_QUEUES: [{"id": 420}]})

    assert unavailable_queues(client) == set()
