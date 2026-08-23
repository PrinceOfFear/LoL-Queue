"""Quem está jogando, segundo o cliente — ou None quando falta algo."""

from lolqueue.core.identity import Identity, current_identity
from lolqueue.lcu.client import LcuError
from lolqueue.lcu.endpoints import CURRENT_SUMMONER, RIOT_REGION_LOCALE

_MISSING = object()


class FakeClient:
    """Devolve uma resposta fixa por rota, ou levanta o que for pedido."""

    def __init__(self, responses: dict):
        self._responses = responses

    def get(self, path):
        value = self._responses.get(path, _MISSING)
        if value is _MISSING:
            raise LcuError(f"rota não configurada no fake: {path}")
        if isinstance(value, Exception):
            raise value
        return value


def test_a_full_response_becomes_an_identity():
    client = FakeClient(
        {
            CURRENT_SUMMONER: {
                "gameName": "Jogador",
                "tagLine": "BR1",
                "summonerLevel": 1098,
            },
            RIOT_REGION_LOCALE: {"region": "BR", "locale": "pt_BR"},
        }
    )

    identity = current_identity(client)

    assert identity == Identity(
        game_name="Jogador", tag_line="BR1", region="BR", level=1098
    )


def test_a_missing_field_returns_none():
    client = FakeClient(
        {
            CURRENT_SUMMONER: {"gameName": "Jogador", "summonerLevel": 1098},
            RIOT_REGION_LOCALE: {"region": "BR"},
        }
    )

    assert current_identity(client) is None


def test_an_lcu_error_returns_none():
    client = FakeClient({CURRENT_SUMMONER: LcuError("cliente fechado")})

    assert current_identity(client) is None
