"""Perfil e histórico de partidas, pelo mesmo servidor MCP do OP.GG.

Reaproveita o parser de `core/mcp_format.py` — a resposta chega no
mesmo formato compacto que a build de campeão. Diferente de
`OpggSource`, aqui **não há cache**: histórico envelhece rápido, ao
contrário de build de campeão, que muda pouco durante uma sessão.

Mesma regra de falha do resto do app: rede fora, campo faltando ou
formato mudado vira `None`/`()`, nunca uma exceção para quem chama.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from . import mcp_format

ENDPOINT = "https://mcp-api.op.gg/mcp"
PROFILE_TOOL = "lol_get_summoner_profile"
MATCHES_TOOL = "lol_list_summoner_matches"
GAME_DETAIL_TOOL = "lol_get_summoner_game_detail"

PROFILE_ROOT = "LolGetSummonerProfile"
MATCHES_ROOT = "LolListSummonerMatches"
GAME_DETAIL_ROOT = "LolGetSummonerGameDetail"

PROFILE_FIELDS = (
    "data.summoner.{game_name,tagline,level}",
    "data.summoner.league_stats[].{game_type,tier_info,win,lose}",
)
MATCH_FIELDS = (
    "data.game_history[].{id,created_at,game_length_second,game_type}",
    "data.game_history[].participants[].{champion_id,champion_name,position,items,items_names,spells}",
    "data.game_history[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}",
    "data.game_history[].participants[].stats.{champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result}",
)
GAME_DETAIL_FIELDS = (
    "data.game_detail.{id,created_at,game_type,game_length_second}",
    "data.game_detail.average_tier_info.tier",
    "data.game_detail.teams[].{key,banned_champions,banned_champions_names}",
    "data.game_detail.teams[].game_stat.{is_win,champion_kill,tower_kill,dragon_kill,baron_kill,rift_herald_kill,gold_earned}",
    "data.game_detail.teams[].participants[].{is_target,champion_id,champion_name,team_key,position,items,items_names,spells}",
    "data.game_detail.teams[].participants[].summoner.{game_name,tagline}",
    "data.game_detail.teams[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}",
    "data.game_detail.teams[].participants[].stats.{champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,total_damage_dealt_to_champions,result}",
)

DEFAULT_LANG = "pt_BR"
# O OP.GG aceita no máximo vinte partidas nesta consulta. Mostrar essa
# janela inteira permite relacionar confirmações oficiais que já saíram
# dos dez jogos mais recentes, sem pedir uma quantidade que o servidor
# simplesmente descartaria.
DEFAULT_LIMIT = 20

LCU_RANK_QUEUE_TYPES = {
    "RANKED_SOLO_5X5": "SOLORANKED",
    "RANKED_FLEX_SR": "FLEXRANKED",
}
ROMAN_DIVISIONS = {"I": 1, "II": 2, "III": 3, "IV": 4}


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


def _native_int(value) -> int | None:
    """Inteiro vindo diretamente do JSON da LCU, sem aceitar ``bool``."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _lcu_division(value) -> int | None:
    if (number := _native_int(value)) is not None:
        return number
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if text.isdecimal():
        return int(text)
    return ROMAN_DIVISIONS.get(text)


def local_rank_entries(payload) -> tuple[RankEntry, ...]:
    """Converte o retrato de ranking atual da LCU em linhas da interface.

    A tela ainda usa o OP.GG para nome, nível e histórico, mas o PDL do
    retrato local é a fonte oficial e chega sem a defasagem do perfil
    público. Só Solo/Duo e Flex entram aqui; filas sem PDL não devem criar
    cartões vazios.
    """

    queues = payload.get("queues") if isinstance(payload, dict) else None
    if not isinstance(queues, list):
        return ()
    found: list[RankEntry] = []
    for row in queues:
        if not isinstance(row, dict):
            continue
        raw_queue = row.get("queueType")
        queue_type = (
            LCU_RANK_QUEUE_TYPES.get(raw_queue.strip().upper())
            if isinstance(raw_queue, str)
            else None
        )
        tier = row.get("tier")
        lp = _native_int(row.get("leaguePoints"))
        if queue_type is None or not isinstance(tier, str) or not tier.strip() or lp is None:
            continue
        found.append(
            RankEntry(
                queue_type=queue_type,
                tier=tier.strip().upper(),
                division=_lcu_division(row.get("division")),
                lp=lp,
                wins=_native_int(row.get("wins")) or 0,
                losses=_native_int(row.get("losses")) or 0,
            )
        )
    return tuple(found)


def with_local_rank_entries(profile: Profile, payload) -> Profile:
    """Troca apenas Solo/Duo e Flex pelos PDL atuais do cliente."""

    local = {entry.queue_type: entry for entry in local_rank_entries(payload)}
    if not local:
        return profile
    ranks = tuple(local.pop(rank.queue_type, rank) for rank in profile.ranks)
    # O perfil público pode demorar para criar uma fila recém-colocada;
    # nesse caso o cliente ainda merece exibi-la imediatamente.
    return replace(profile, ranks=ranks + tuple(local.values()))


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
    items: tuple[int, ...]
    item_names: tuple[str, ...]
    spells: tuple[int, int]
    primary_style_id: int
    primary_rune_id: int
    secondary_style_id: int
    champion_level: int
    gold: int
    #: Delta oficial do cliente, quando ainda existe uma confirmação.
    #: `None` é intencional: partidas antigas não recebem estimativa.
    lp_delta: int | None = None
    lp_after: int | None = None
    lp_queue: str = ""
    #: Origem do PDL: evento Riot, snapshot local ou preenchimento manual.
    #: Fica vazio quando ainda não há um delta salvo para a linha.
    lp_source: str = ""
    #: Id numérico confirmado pela LCU para esta linha do OP.GG. É efêmero
    #: na tela e serve para validar uma eventual importação manual.
    local_game_id: int | None = None


@dataclass(frozen=True)
class ParticipantDetail:
    """Uma linha do placar completo — qualquer um dos dez jogadores."""

    is_target: bool
    game_name: str
    tag_line: str
    champion_id: int
    champion_name: str
    team_key: str
    position: str
    items: tuple[int, ...]
    item_names: tuple[str, ...]
    spells: tuple[int, int]
    primary_style_id: int
    primary_rune_id: int
    secondary_style_id: int
    champion_level: int
    kills: int
    deaths: int
    assists: int
    cs: int
    gold: int
    damage_to_champions: int
    result: str


@dataclass(frozen=True)
class TeamDetail:
    """Um dos dois lados: banimentos, objetivos e os cinco jogadores."""

    key: str
    win: bool
    kills: int
    towers: int
    dragons: int
    barons: int
    heralds: int
    gold: int
    banned_champion_ids: tuple[int, ...]
    banned_champion_names: tuple[str, ...]
    participants: tuple[ParticipantDetail, ...]


@dataclass(frozen=True)
class GameDetail:
    """O placar completo de uma partida — a aba "Placar" do cliente."""

    match_id: str
    duration_seconds: int
    queue_type: str
    played_at: datetime
    teams: tuple[TeamDetail, TeamDetail]
    average_tier: str | None
    #: Repassado da linha que abriu este placar.
    lp_delta: int | None = None
    #: A mesma origem mostrada na lista; evita chamar de oficial um valor
    #: que foi informado manualmente pelo jogador.
    lp_source: str = ""


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
        items = mcp_format.to_ints(fields.get("items", "[]"))
        spells = mcp_format.to_ints(fields.get("spells", "[]"))
        rune = mcp_format.unpack(fields.get("rune"), schema)
        stats = mcp_format.unpack(fields.get("stats"), schema)
        if (
            champion_id is None
            or not champion_name
            or items is None
            or spells is None
            or len(spells) != 2
            or rune is None
            or stats is None
        ):
            continue
        primary_style_id = mcp_format.to_int(rune.get("primary_page_id", ""))
        primary_rune_id = mcp_format.to_int(rune.get("primary_rune_id", ""))
        secondary_style_id = mcp_format.to_int(rune.get("secondary_page_id", ""))
        champion_level = mcp_format.to_int(stats.get("champion_level", ""))
        kills = mcp_format.to_int(stats.get("kill", ""))
        deaths = mcp_format.to_int(stats.get("death", ""))
        assists = mcp_format.to_int(stats.get("assist", ""))
        minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
        neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
        gold = mcp_format.to_int(stats.get("gold_earned", ""))
        result = stats.get("result", "").strip().strip('"')
        if (
            primary_style_id is None
            or primary_rune_id is None
            or secondary_style_id is None
            or champion_level is None
            or kills is None
            or deaths is None
            or assists is None
            or gold is None
            or not result
        ):
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
                items=tuple(items),
                item_names=tuple(mcp_format.to_strings(fields.get("items_names", ""))),
                spells=(spells[0], spells[1]),
                primary_style_id=primary_style_id,
                primary_rune_id=primary_rune_id,
                secondary_style_id=secondary_style_id,
                champion_level=champion_level,
                gold=gold,
            )
        )
        if len(found) >= limit:
            break
    return tuple(found)


def _participant_detail(value: str, schema: dict[str, list[str]]) -> ParticipantDetail | None:
    fields = mcp_format.unpack(value, schema)
    if fields is None:
        return None
    summoner = mcp_format.unpack(fields.get("summoner"), schema)
    rune = mcp_format.unpack(fields.get("rune"), schema)
    stats = mcp_format.unpack(fields.get("stats"), schema)
    if summoner is None or rune is None or stats is None:
        return None
    is_target = mcp_format.to_bool(fields.get("is_target", ""))
    game_name = summoner.get("game_name", "").strip().strip('"')
    tag_line = summoner.get("tagline", "").strip().strip('"')
    champion_id = mcp_format.to_int(fields.get("champion_id", ""))
    champion_name = fields.get("champion_name", "").strip().strip('"')
    team_key = fields.get("team_key", "").strip().strip('"')
    position = fields.get("position", "").strip().strip('"')
    items = mcp_format.to_ints(fields.get("items", "[]"))
    spells = mcp_format.to_ints(fields.get("spells", "[]"))
    if (
        is_target is None
        or not game_name
        or not tag_line
        or champion_id is None
        or not champion_name
        or not team_key
        or items is None
        or spells is None
        or len(spells) != 2
    ):
        return None
    primary_style_id = mcp_format.to_int(rune.get("primary_page_id", ""))
    primary_rune_id = mcp_format.to_int(rune.get("primary_rune_id", ""))
    secondary_style_id = mcp_format.to_int(rune.get("secondary_page_id", ""))
    champion_level = mcp_format.to_int(stats.get("champion_level", ""))
    kills = mcp_format.to_int(stats.get("kill", ""))
    deaths = mcp_format.to_int(stats.get("death", ""))
    assists = mcp_format.to_int(stats.get("assist", ""))
    minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
    neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
    gold = mcp_format.to_int(stats.get("gold_earned", ""))
    damage = mcp_format.to_int(stats.get("total_damage_dealt_to_champions", ""))
    result = stats.get("result", "").strip().strip('"')
    if (
        primary_style_id is None
        or primary_rune_id is None
        or secondary_style_id is None
        or champion_level is None
        or kills is None
        or deaths is None
        or assists is None
        or gold is None
        or damage is None
        or not result
    ):
        return None
    return ParticipantDetail(
        is_target=is_target,
        game_name=game_name,
        tag_line=tag_line,
        champion_id=champion_id,
        champion_name=champion_name,
        team_key=team_key,
        position=position,
        items=tuple(items),
        item_names=tuple(mcp_format.to_strings(fields.get("items_names", ""))),
        spells=(spells[0], spells[1]),
        primary_style_id=primary_style_id,
        primary_rune_id=primary_rune_id,
        secondary_style_id=secondary_style_id,
        champion_level=champion_level,
        kills=kills,
        deaths=deaths,
        assists=assists,
        cs=minions + neutral,
        gold=gold,
        damage_to_champions=damage,
        result=result,
    )


def _team_detail(value: str, schema: dict[str, list[str]]) -> TeamDetail | None:
    fields = mcp_format.unpack(value, schema)
    if fields is None:
        return None
    key = fields.get("key", "").strip().strip('"')
    game_stat = mcp_format.unpack(fields.get("game_stat"), schema)
    if not key or game_stat is None:
        return None
    win = mcp_format.to_bool(game_stat.get("is_win", ""))
    kills = mcp_format.to_int(game_stat.get("champion_kill", ""))
    towers = mcp_format.to_int(game_stat.get("tower_kill", ""))
    dragons = mcp_format.to_int(game_stat.get("dragon_kill", ""))
    barons = mcp_format.to_int(game_stat.get("baron_kill", ""))
    heralds = mcp_format.to_int(game_stat.get("rift_herald_kill", ""))
    gold = mcp_format.to_int(game_stat.get("gold_earned", ""))
    banned_ids = mcp_format.to_ints(fields.get("banned_champions", "[]"))
    banned_names = mcp_format.to_strings(fields.get("banned_champions_names", ""))
    if (
        win is None
        or kills is None
        or towers is None
        or dragons is None
        or barons is None
        or heralds is None
        or gold is None
        or banned_ids is None
    ):
        return None
    participants = tuple(
        detail
        for detail in (
            _participant_detail(entry, schema)
            for entry in mcp_format.entries(fields.get("participants", ""))
        )
        if detail is not None
    )
    if len(participants) != 5:
        return None
    return TeamDetail(
        key=key,
        win=win,
        kills=kills,
        towers=towers,
        dragons=dragons,
        barons=barons,
        heralds=heralds,
        gold=gold,
        banned_champion_ids=tuple(banned_ids),
        banned_champion_names=tuple(banned_names),
        participants=participants,
    )


def _game_detail(text: str) -> GameDetail | None:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, GAME_DETAIL_ROOT)
    if data is None:
        return None
    game = mcp_format.unpack(data.get("game_detail"), schema)
    if game is None:
        return None
    match_id = game.get("id", "").strip().strip('"')
    created_at = game.get("created_at", "").strip().strip('"')
    duration = mcp_format.to_int(game.get("game_length_second", ""))
    queue_type = game.get("game_type", "").strip().strip('"')
    if not match_id or not created_at or duration is None:
        return None
    try:
        played_at = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    teams = tuple(
        team
        for team in (
            _team_detail(entry, schema) for entry in mcp_format.entries(game.get("teams", ""))
        )
        if team is not None
    )
    if len(teams) != 2:
        return None
    tier_fields = mcp_format.unpack(game.get("average_tier_info"), schema) or {}
    tier_raw = tier_fields.get("tier", "").strip()
    average_tier = tier_raw.strip('"') if tier_raw and tier_raw != "null" else None
    return GameDetail(
        match_id=match_id,
        duration_seconds=duration,
        queue_type=queue_type,
        played_at=played_at,
        teams=(teams[0], teams[1]),
        average_tier=average_tier,
    )


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

    def fetch_game_detail(
        self,
        match_id: str,
        played_at: datetime,
        region: str,
        game_name: str,
        tag_line: str,
        lang: str = DEFAULT_LANG,
    ) -> GameDetail | None:
        if not match_id or not region or not game_name or not tag_line:
            return None
        try:
            text = self._send(
                GAME_DETAIL_TOOL,
                {
                    "region": region,
                    "game_id": match_id,
                    "created_at": played_at.isoformat(),
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "focus_riot_id": f"{game_name}#{tag_line}",
                    "lang": lang,
                    "desired_output_fields": list(GAME_DETAIL_FIELDS),
                },
            )
        except Exception:
            return None
        return _game_detail(text or "")
