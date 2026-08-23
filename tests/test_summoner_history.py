"""Perfil e histórico de partidas: leitura da resposta real do OP.GG.

As respostas embutidas abaixo foram capturadas ao vivo contra
`mcp-api.op.gg`, com o nome e a tag trocados por valores fictícios — o
resto (elos, KDA, ids de campeão, timestamps) é o dado real que o
servidor devolveu.
"""

from datetime import datetime, timezone

from lolqueue.core.summoner_history import (
    MatchSummary,
    Profile,
    RankEntry,
    SummonerHistorySource,
    relative_time,
)

PROFILE = """class LolGetSummonerProfile: data
class Data: summoner
class Summoner: game_name,tagline,level,league_stats
class LeagueStat: game_type,tier_info,win,lose
class TierInfo: tier,division,lp,level,tier_image_url,border_image_url

LolGetSummonerProfile(Data(Summoner("Jogador","BR1",1098,[LeagueStat("SOLORANKED",TierInfo("EMERALD",3,53,null,"https://opgg-static.akamaized.net/images/medals_new/emerald.png","https://opgg-static.akamaized.net/images/border_new/emerald.png"),602,602),LeagueStat("FLEXRANKED",TierInfo("PLATINUM",3,46,null,"https://opgg-static.akamaized.net/images/medals_new/platinum.png","https://opgg-static.akamaized.net/images/border_new/platinum.png"),83,92),LeagueStat("ARENA",TierInfo(null,null,null,null,"https://opgg-static.akamaized.net/images/medals_new/default_unranked.svg",null),null,null)])))"""

BROKEN_PROFILE = """class LolGetSummonerProfile: data
class Data: summoner
class Summoner: game_name,tagline,league_stats
class LeagueStat: game_type,tier_info,win,lose
class TierInfo: tier,division,lp,level,tier_image_url,border_image_url

LolGetSummonerProfile(Data(Summoner("Jogador","BR1",[])))"""

MATCHES = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,stats
class Stats: kill,death,assist,minion_kill,neutral_minion_kill,result

LolListSummonerMatches(Data([GameHistory("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,[Participant(54,"Malphite","TOP",Stats(0,4,0,79,0,"LOSE"))]),GameHistory("wgqT90Iiz731oz69P0WgLhMo6OGiXESPtevq3Dx7SlQ=","2026-08-23T16:25:39+09:00","SOLORANKED",1686,[Participant(22,"Ashe","ADC",Stats(6,6,12,176,12,"WIN"))])]))"""


class FakeSend:
    """Substitui a ida à rede: devolve a resposta certa por ferramenta."""

    def __init__(self, profile_answer="", matches_answer="", fail=False):
        self.profile_answer = profile_answer
        self.matches_answer = matches_answer
        self.fail = fail
        self.calls = []

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.fail:
            raise OSError("sem rede")
        if tool == "lol_get_summoner_profile":
            return self.profile_answer
        return self.matches_answer


# --- perfil -----------------------------------------------------------


def test_a_full_profile_reads_name_level_and_ranks():
    source = SummonerHistorySource(send=FakeSend(profile_answer=PROFILE))

    profile = source.fetch_profile("Jogador", "BR1", "BR")

    assert profile == Profile(
        game_name="Jogador",
        tag_line="BR1",
        level=1098,
        ranks=(
            RankEntry("SOLORANKED", "EMERALD", 3, 53, 602, 602),
            RankEntry("FLEXRANKED", "PLATINUM", 3, 46, 83, 92),
            RankEntry("ARENA", None, None, None, 0, 0),
        ),
    )


def test_an_empty_response_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(profile_answer=""))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_a_missing_field_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(profile_answer=BROKEN_PROFILE))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_a_network_failure_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_without_identity_no_request_is_made():
    send = FakeSend(profile_answer=PROFILE)
    source = SummonerHistorySource(send=send)

    assert source.fetch_profile("", "BR1", "BR") is None
    assert send.calls == []


# --- partidas -----------------------------------------------------------


def test_matches_read_a_win_and_a_loss_with_kda_and_cs():
    source = SummonerHistorySource(send=FakeSend(matches_answer=MATCHES))

    matches = source.fetch_matches("Jogador", "BR1", "BR")

    assert matches == (
        MatchSummary(
            match_id="wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
            champion_id=54,
            champion_name="Malphite",
            result="LOSE",
            kills=0,
            deaths=4,
            assists=0,
            cs=79,
            duration_seconds=958,
            queue_type="SOLORANKED",
            position="TOP",
            played_at=datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        ),
        MatchSummary(
            match_id="wgqT90Iiz731oz69P0WgLhMo6OGiXESPtevq3Dx7SlQ=",
            champion_id=22,
            champion_name="Ashe",
            result="WIN",
            kills=6,
            deaths=6,
            assists=12,
            cs=188,
            duration_seconds=1686,
            queue_type="SOLORANKED",
            position="ADC",
            played_at=datetime.fromisoformat("2026-08-23T16:25:39+09:00"),
        ),
    )


def test_an_empty_response_means_no_matches():
    source = SummonerHistorySource(send=FakeSend(matches_answer=""))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()


def test_a_network_failure_means_no_matches():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()


def test_the_limit_is_forwarded_to_the_request():
    send = FakeSend(matches_answer=MATCHES)
    source = SummonerHistorySource(send=send)

    source.fetch_matches("Jogador", "BR1", "BR", limit=10)

    tool, arguments = send.calls[0]
    assert tool == "lol_list_summoner_matches"
    assert arguments["limit"] == 10


# --- tempo relativo -------------------------------------------------------


def test_a_match_from_seconds_ago_reads_as_now():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 0, 30, tzinfo=timezone.utc)

    assert relative_time(played, now) == "agora"


def test_a_match_from_minutes_ago():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 25, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 25 min"


def test_a_match_from_hours_ago():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 15, 0, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 3 h"


def test_a_match_from_days_ago():
    played = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 3 dias"
