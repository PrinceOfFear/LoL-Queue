"""Quem está jogando, segundo o próprio cliente do LoL.

Junta dois endpoints que sozinhos não bastam: o nome e o nível vêm de
`current-summoner`, e a região — que o OP.GG exige no formato de sigla
("BR", "KR") — só aparece em `region-locale`, uma rota do Riot Client
servida pela mesma conexão.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..lcu import endpoints
from ..lcu.client import LcuError


@dataclass(frozen=True)
class Identity:
    game_name: str
    tag_line: str
    region: str
    level: int


def current_identity(client) -> Identity | None:
    """Lê quem está conectado agora, ou `None` se algo faltar ou falhar.

    Cliente fechado, sessão ainda não pronta ou resposta incompleta são
    todos o mesmo caso para quem chama: sem identidade, não há como
    perguntar nada ao OP.GG.
    """
    try:
        summoner = client.get(endpoints.CURRENT_SUMMONER)
        locale = client.get(endpoints.RIOT_REGION_LOCALE)
    except LcuError:
        return None
    if not isinstance(summoner, dict) or not isinstance(locale, dict):
        return None

    game_name = summoner.get("gameName")
    tag_line = summoner.get("tagLine")
    level = summoner.get("summonerLevel")
    region = locale.get("region")
    if not game_name or not tag_line or not region or level is None:
        return None
    return Identity(game_name=game_name, tag_line=tag_line, region=region, level=level)
