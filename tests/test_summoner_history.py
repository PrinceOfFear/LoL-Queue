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
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,[Participant(54,"Malphite","TOP",[1056,3802,1001,1029,1026],["Anel de Doran","Capítulo Perdido","Botas","Couraça de Pano","Varinha Explosiva"],Rune(8200,8229,8400),[4,12],Stats(10,0,4,0,79,0,3901,"LOSE"))]),GameHistory("wgqT90Iiz72Bsm3unOefxkCMsMc-e8bCFWQ9MpHIUIo=","2026-08-23T16:56:57+09:00","SOLORANKED",1522,[Participant(22,"Ashe","ADC",[1086,3153,2003,3085,3123],["Arco de Doran","Espada do Rei Destruído","Poção de Vida","Furacão de Runaan","Chamado do Carrasco"],Rune(8000,8008,8300),[4,21],Stats(13,4,12,2,155,4,8902,"LOSE"))])]))"""


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
            items=(1056, 3802, 1001, 1029, 1026),
            item_names=(
                "Anel de Doran",
                "Capítulo Perdido",
                "Botas",
                "Couraça de Pano",
                "Varinha Explosiva",
            ),
            spells=(4, 12),
            primary_style_id=8200,
            primary_rune_id=8229,
            secondary_style_id=8400,
            champion_level=10,
            gold=3901,
        ),
        MatchSummary(
            match_id="wgqT90Iiz72Bsm3unOefxkCMsMc-e8bCFWQ9MpHIUIo=",
            champion_id=22,
            champion_name="Ashe",
            result="LOSE",
            kills=4,
            deaths=12,
            assists=2,
            cs=159,
            duration_seconds=1522,
            queue_type="SOLORANKED",
            position="ADC",
            played_at=datetime.fromisoformat("2026-08-23T16:56:57+09:00"),
            items=(1086, 3153, 2003, 3085, 3123),
            item_names=(
                "Arco de Doran",
                "Espada do Rei Destruído",
                "Poção de Vida",
                "Furacão de Runaan",
                "Chamado do Carrasco",
            ),
            spells=(4, 21),
            primary_style_id=8000,
            primary_rune_id=8008,
            secondary_style_id=8300,
            champion_level=13,
            gold=8902,
        ),
    )


def test_items_come_in_whatever_length_the_match_really_has():
    """A grade da linha desenha o que a partida comprou — sem casas
    fixas para itens que nunca foram comprados."""
    answer = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("id1","2026-08-23T12:00:00+00:00","ARAM",600,[Participant(1,"Annie","MID",[1001,3020],["Botas","Sapatos Enfeitiçados"],Rune(8100,8112,8000),[4,14],Stats(6,2,3,1,40,0,2500,"WIN"))])]))"""
    source = SummonerHistorySource(send=FakeSend(matches_answer=answer))

    matches = source.fetch_matches("Jogador", "BR1", "BR")

    assert matches[0].items == (1001, 3020)
    assert matches[0].item_names == ("Botas", "Sapatos Enfeitiçados")
    assert matches[0].spells == (4, 14)


def test_a_match_missing_rune_data_is_discarded():
    """Sem runa não dá para desenhar a grade — a partida some da lista,
    não aparece pela metade. Mesma regra de tolerância do resto do
    parser."""
    answer = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("id1","2026-08-23T12:00:00+00:00","ARAM",600,[Participant(1,"Annie","MID",[1001],["Botas"],Rune(8100,8112),[4,14],Stats(6,2,3,1,40,0,2500,"WIN"))])]))"""
    source = SummonerHistorySource(send=FakeSend(matches_answer=answer))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()


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
