"""Perfil e histórico de partidas, pelo mesmo servidor MCP do OP.GG.

Reaproveita o parser de `core/mcp_format.py` — a resposta chega no
mesmo formato compacto que a build de campeão. Diferente de
`OpggSource`, aqui **não há cache**: histórico envelhece rápido, ao
contrário de build de campeão, que muda pouco durante uma sessão.

Mesma regra de falha do resto do app: rede fora, campo faltando ou
formato mudado vira `None`/`()`, nunca uma exceção para quem chama.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import mcp_format

ENDPOINT = "https://mcp-api.op.gg/mcp"
PROFILE_TOOL = "lol_get_summoner_profile"
MATCHES_TOOL = "lol_list_summoner_matches"

PROFILE_ROOT = "LolGetSummonerProfile"
MATCHES_ROOT = "LolListSummonerMatches"

PROFILE_FIELDS = (
    "data.summoner.{game_name,tagline,level}",
    "data.summoner.league_stats[].{game_type,tier_info,win,lose}",
)
MATCH_FIELDS = (
    "data.game_history[].{id,created_at,game_length_second,game_type}",
    "data.game_history[].participants[].{champion_id,champion_name,position}",
    "data.game_history[].participants[].stats.{kill,death,assist,minion_kill,neutral_minion_kill,result}",
)

DEFAULT_LANG = "pt_BR"
DEFAULT_LIMIT = 10


@dataclass(frozen=True)
class RankEntry:
    """O boletim de uma fila: elo, divisão, PDL e o retrospecto.

    `tier` vem `None` quando a fila não tem elo — o ARENA do OP.GG
    sempre chega assim, e as ranqueadas chegam assim antes da
    colocação.
    """

    queue_type: str
    tier: str | None
    division: int | None
    lp: int | None
    wins: int
    losses: int


@dataclass(frozen=True)
class Profile:
    game_name: str
    tag_line: str
    level: int
    ranks: tuple[RankEntry, ...] = ()


@dataclass(frozen=True)
class MatchSummary:
    """Uma partida, já filtrada pelo servidor para o jogador buscado."""

    match_id: str
    champion_id: int
    #: Em inglês, como o OP.GG manda. A UI troca pelo nome em
    #: português do catálogo já carregado, quando existir.
    champion_name: str
    result: str  # "WIN" | "LOSE"
    kills: int
    deaths: int
    assists: int
    cs: int
    duration_seconds: int
    queue_type: str
    position: str
    played_at: datetime


def relative_time(played_at: datetime, now: datetime) -> str:
    """Há quanto tempo foi jogada: "agora", "há N min", "há N h", "há N dias"."""
    minutes = int((now - played_at).total_seconds() // 60)
    if minutes < 1:
        return "agora"
    if minutes < 60:
        return f"há {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"há {hours} h"
    days = hours // 24
    return f"há {days} dias"


def _rank_entries(value: str, schema: dict[str, list[str]]) -> tuple[RankEntry, ...]:
    found: list[RankEntry] = []
    for entry in mcp_format.entries(value):
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        queue_type = fields.get("game_type", "").strip().strip('"')
        if not queue_type:
            continue
        tier_fields = mcp_format.unpack(fields.get("tier_info"), schema) or {}
        tier_raw = tier_fields.get("tier", "").strip()
        tier = tier_raw.strip('"') if tier_raw and tier_raw != "null" else None
        found.append(
            RankEntry(
                queue_type=queue_type,
                tier=tier,
                division=mcp_format.to_int(tier_fields.get("division", "")),
                lp=mcp_format.to_int(tier_fields.get("lp", "")),
                wins=mcp_format.to_int(fields.get("win", "")) or 0,
                losses=mcp_format.to_int(fields.get("lose", "")) or 0,
            )
        )
    return tuple(found)


def _profile(text: str) -> Profile | None:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, PROFILE_ROOT)
    if data is None:
        return None
    summoner = mcp_format.unpack(data.get("summoner"), schema)
    if summoner is None:
        return None
    game_name = summoner.get("game_name", "").strip().strip('"')
    tag_line = summoner.get("tagline", "").strip().strip('"')
    level = mcp_format.to_int(summoner.get("level", ""))
    if not game_name or not tag_line or level is None:
        return None
    return Profile(
        game_name=game_name,
        tag_line=tag_line,
        level=level,
        ranks=_rank_entries(summoner.get("league_stats", ""), schema),
    )


def _match_summaries(text: str, limit: int) -> tuple[MatchSummary, ...]:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, MATCHES_ROOT)
    if data is None:
        return ()
    found: list[MatchSummary] = []
    for entry in mcp_format.entries(data.get("game_history", "")):
        game = mcp_format.unpack(entry, schema)
        if game is None:
            continue
        match_id = game.get("id", "").strip().strip('"')
        created_at = game.get("created_at", "").strip().strip('"')
        duration = mcp_format.to_int(game.get("game_length_second", ""))
        queue_type = game.get("game_type", "").strip().strip('"')
        participant = mcp_format.first(game.get("participants"))
        fields = mcp_format.unpack(participant, schema) if participant else None
        if fields is None or duration is None or not match_id or not created_at:
            continue
        champion_id = mcp_format.to_int(fields.get("champion_id", ""))
        champion_name = fields.get("champion_name", "").strip().strip('"')
        position = fields.get("position", "").strip().strip('"')
        stats = mcp_format.unpack(fields.get("stats"), schema)
        if champion_id is None or not champion_name or stats is None:
            continue
        kills = mcp_format.to_int(stats.get("kill", ""))
        deaths = mcp_format.to_int(stats.get("death", ""))
        assists = mcp_format.to_int(stats.get("assist", ""))
        minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
        neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
        result = stats.get("result", "").strip().strip('"')
        if kills is None or deaths is None or assists is None or not result:
            continue
        try:
            played_at = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        found.append(
            MatchSummary(
                match_id=match_id,
                champion_id=champion_id,
                champion_name=champion_name,
                result=result,
                kills=kills,
                deaths=deaths,
                assists=assists,
                cs=minions + neutral,
                duration_seconds=duration,
                queue_type=queue_type,
                position=position,
                played_at=played_at,
            )
        )
        if len(found) >= limit:
            break
    return tuple(found)


def _send(tool: str, arguments: dict) -> str:
    return mcp_format.send_tool(ENDPOINT, tool, arguments)


class SummonerHistorySource:
    """Busca perfil e partidas recentes. Sem cache: o dado envelhece rápido."""

    def __init__(self, send: Callable[[str, dict], str] | None = None) -> None:
        self._send = send or _send

    def fetch_profile(
        self, game_name: str, tag_line: str, region: str, lang: str = DEFAULT_LANG
    ) -> Profile | None:
        if not game_name or not tag_line or not region:
            return None
        try:
            text = self._send(
                PROFILE_TOOL,
                {
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "region": region,
                    "lang": lang,
                    "desired_output_fields": list(PROFILE_FIELDS),
                },
            )
        except Exception:
            return None
        return _profile(text or "")

    def fetch_matches(
        self,
        game_name: str,
        tag_line: str,
        region: str,
        lang: str = DEFAULT_LANG,
        limit: int = DEFAULT_LIMIT,
    ) -> tuple[MatchSummary, ...]:
        if not game_name or not tag_line or not region:
            return ()
        try:
            text = self._send(
                MATCHES_TOOL,
                {
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "region": region,
                    "lang": lang,
                    "limit": limit,
                    "desired_output_fields": list(MATCH_FIELDS),
                },
            )
        except Exception:
            return ()
        return _match_summaries(text or "", limit)
