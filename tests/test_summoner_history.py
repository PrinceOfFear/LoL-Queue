"""Perfil e histórico de partidas: leitura da resposta real do OP.GG.

As respostas embutidas abaixo foram capturadas ao vivo contra
`mcp-api.op.gg`, com o nome e a tag trocados por valores fictícios — o
resto (elos, KDA, ids de campeão, timestamps) é o dado real que o
servidor devolveu.
"""

from datetime import datetime, timezone

from lolqueue.core.summoner_history import (
    GameDetail,
    MatchSummary,
    ParticipantDetail,
    Profile,
    RankEntry,
    SummonerHistorySource,
    TeamDetail,
    with_local_rank_entries,
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


def test_the_local_client_rank_replaces_a_stale_public_lp_value():
    public = Profile(
        game_name="Jogador",
        tag_line="BR1",
        level=1098,
        ranks=(
            RankEntry("SOLORANKED", "GOLD", 2, 0, 4, 5),
            RankEntry("ARENA", None, None, None, 0, 0),
        ),
    )
    current = {
        "queues": [
            {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "GOLD",
                "division": "II",
                "leaguePoints": 48,
                "wins": 75,
                "losses": 79,
            },
            {
                "queueType": "RANKED_FLEX_SR",
                "tier": "GOLD",
                "division": "II",
                "leaguePoints": 86,
                "wins": 205,
                "losses": 195,
            },
            {"queueType": "RANKED_TFT", "leaguePoints": 0},
        ]
    }

    merged = with_local_rank_entries(public, current)

    assert merged.ranks == (
        RankEntry("SOLORANKED", "GOLD", 2, 48, 75, 79),
        RankEntry("ARENA", None, None, None, 0, 0),
        RankEntry("FLEXRANKED", "GOLD", 2, 86, 205, 195),
    )


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


def test_the_default_history_window_uses_the_maximum_supported_by_the_source():
    send = FakeSend(matches_answer=MATCHES)
    source = SummonerHistorySource(send=send)

    source.fetch_matches("Jogador", "BR1", "BR")

    _, arguments = send.calls[0]
    assert arguments["limit"] == 20


# --- placar completo -----------------------------------------------------

GAME_DETAIL = """class LolGetSummonerGameDetail: data
class Data: game_detail
class GameDetail: id,created_at,game_type,game_length_second,average_tier_info,teams
class AverageTierInfo: tier,division
class Team: key,game_stat,banned_champions,banned_champions_names,participants
class GameStat: is_win,champion_kill,tower_kill,dragon_kill,baron_kill,rift_herald_kill,gold_earned
class Participant: is_target,summoner,champion_id,champion_name,team_key,position,items,items_names,rune,spells,stats
class Summoner: game_name,tagline
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,total_damage_dealt_to_champions,result

LolGetSummonerGameDetail(Data(GameDetail("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,AverageTierInfo("EMERALD",2),[Team("BLUE",GameStat(false,8,0,0,0,0,24155),[25,55,141,412,910],["Morgana","Katarina","Kayn","Thresh","Hwei"],[Participant(false,Summoner("Aliado1","BR1"),200,"Bel'Veth","BLUE","JUNGLE",[1102,6672,1001,2152,1043],["Cria de Andabrisas","Mata-Cráquens","Botas","Elixir da Força","Arco Recurvo"],Rune(8000,8008,8300),[4,11],Stats(8,1,9,0,2,74,4735,2682,"LOSE")),Participant(true,Summoner("Jogador","BR1"),54,"Malphite","BLUE","TOP",[1056,3802,1001,1029,1026],["Anel de Doran","Capítulo Perdido","Botas","Couraça de Pano","Varinha Explosiva"],Rune(8200,8229,8400),[4,12],Stats(10,0,4,0,79,0,3901,4790,"LOSE")),Participant(false,Summoner("Aliado2","BR1"),800,"Mel","BLUE","MID",[6655,3145,1001],["Eco de Luden","Alternador Hextec","Botas"],Rune(8200,8229,8000),[12,4],Stats(10,3,5,2,107,0,4981,8128,"LOSE")),Participant(false,Summoner("Aliado3","BR1"),427,"Ivern","BLUE","SUPPORT",[3870,6617,3158],["Criassonhos","Regenerador de Pedra Lunar","Botas Ionianas da Lucidez"],Rune(8200,8214,8400),[7,4],Stats(7,1,7,4,9,0,4048,2590,"LOSE")),Participant(false,Summoner("Aliado4","BR1"),222,"Jinx","BLUE","ADC",[3144,2523,1086,3086],["Estilingue do Patrulheiro","Hexótica C44","Arco de Doran","Zelo"],Rune(8000,8008,8300),[21,4],Stats(9,3,5,1,116,0,6490,7360,"LOSE"))]),Team("RED",GameStat(true,30,3,1,0,0,36881),[33,117,134,164,238],["Rammus","Lulu","Syndra","Camille","Zed"],[Participant(false,Summoner("Rival1","BR1"),58,"Renekton","RED","TOP",[1055,2031,6692,3111,2021],["Lâmina de Doran","Poção com Refil","Eclipse","Passos de Mercúrio","Tunelizador"],Rune(8000,8010,8400),[4,14],Stats(13,7,0,2,151,2,8471,11033,"WIN")),Participant(false,Summoner("Rival2","BR1"),81,"Ezreal","RED","ADC",[1086,3078,3133,1036,3070],["Arco de Doran","Força da Trindade","Martelo de Guerra de Caulfield","Espada Longa","Lágrima da Deusa"],Rune(8000,8005,8300),[7,4],Stats(11,7,1,3,125,0,8035,10519,"WIN")),Participant(false,Summoner("Rival3","BR1"),526,"Rell","RED","SUPPORT",[3869,3047,3190,1028,1029,1029],["Oposição Celestial","Botas Galvanizadas de Aço","Medalhão dos Solari de Ferro","Cristal de Rubi","Couraça de Pano","Couraça de Pano"],Rune(8400,8439,8300),[4,14],Stats(8,1,5,15,20,0,5317,5007,"WIN")),Participant(false,Summoner("Rival4","BR1"),711,"Vex","RED","MID",[1056,6655,3175,1058,2055],["Anel de Doran","Eco de Luden","Sapatos Enfeitiçados","Bastão Desnecessariamente Grande","Sentinela de Controle"],Rune(8100,8112,8200),[4,14],Stats(11,8,1,5,107,0,7420,11181,"WIN")),Participant(false,Summoner("Rival5","BR1"),234,"Viego","RED","JUNGLE",[6676,6672,1001,1018],["A Coletora","Mata-Cráquens","Botas","Capa da Agilidade"],Rune(8100,9923,8000),[11,4],Stats(11,7,1,5,4,117,7638,9061,"WIN"))])])))"""


def test_fetch_game_detail_reads_both_teams_bans_and_the_target_row():
    send = FakeSend(matches_answer=GAME_DETAIL)
    source = SummonerHistorySource(send=send)

    detail = source.fetch_game_detail(
        "wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
        datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        "BR",
        "Jogador",
        "BR1",
    )

    assert detail == GameDetail(
        match_id="wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
        duration_seconds=958,
        queue_type="SOLORANKED",
        played_at=datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        teams=(
            TeamDetail(
                key="BLUE",
                win=False,
                kills=8,
                towers=0,
                dragons=0,
                barons=0,
                heralds=0,
                gold=24155,
                banned_champion_ids=(25, 55, 141, 412, 910),
                banned_champion_names=("Morgana", "Katarina", "Kayn", "Thresh", "Hwei"),
                participants=(
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado1",
                        tag_line="BR1",
                        champion_id=200,
                        champion_name="Bel'Veth",
                        team_key="BLUE",
                        position="JUNGLE",
                        items=(1102, 6672, 1001, 2152, 1043),
                        item_names=(
                            "Cria de Andabrisas",
                            "Mata-Cráquens",
                            "Botas",
                            "Elixir da Força",
                            "Arco Recurvo",
                        ),
                        spells=(4, 11),
                        primary_style_id=8000,
                        primary_rune_id=8008,
                        secondary_style_id=8300,
                        champion_level=8,
                        kills=1,
                        deaths=9,
                        assists=0,
                        cs=76,
                        gold=4735,
                        damage_to_champions=2682,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=True,
                        game_name="Jogador",
                        tag_line="BR1",
                        champion_id=54,
                        champion_name="Malphite",
                        team_key="BLUE",
                        position="TOP",
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
                        kills=0,
                        deaths=4,
                        assists=0,
                        cs=79,
                        gold=3901,
                        damage_to_champions=4790,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado2",
                        tag_line="BR1",
                        champion_id=800,
                        champion_name="Mel",
                        team_key="BLUE",
                        position="MID",
                        items=(6655, 3145, 1001),
                        item_names=("Eco de Luden", "Alternador Hextec", "Botas"),
                        spells=(12, 4),
                        primary_style_id=8200,
                        primary_rune_id=8229,
                        secondary_style_id=8000,
                        champion_level=10,
                        kills=3,
                        deaths=5,
                        assists=2,
                        cs=107,
                        gold=4981,
                        damage_to_champions=8128,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado3",
                        tag_line="BR1",
                        champion_id=427,
                        champion_name="Ivern",
                        team_key="BLUE",
                        position="SUPPORT",
                        items=(3870, 6617, 3158),
                        item_names=(
                            "Criassonhos",
                            "Regenerador de Pedra Lunar",
                            "Botas Ionianas da Lucidez",
                        ),
                        spells=(7, 4),
                        primary_style_id=8200,
                        primary_rune_id=8214,
                        secondary_style_id=8400,
                        champion_level=7,
                        kills=1,
                        deaths=7,
                        assists=4,
                        cs=9,
                        gold=4048,
                        damage_to_champions=2590,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado4",
                        tag_line="BR1",
                        champion_id=222,
                        champion_name="Jinx",
                        team_key="BLUE",
                        position="ADC",
                        items=(3144, 2523, 1086, 3086),
                        item_names=(
                            "Estilingue do Patrulheiro",
                            "Hexótica C44",
                            "Arco de Doran",
                            "Zelo",
                        ),
                        spells=(21, 4),
                        primary_style_id=8000,
                        primary_rune_id=8008,
                        secondary_style_id=8300,
                        champion_level=9,
                        kills=3,
                        deaths=5,
                        assists=1,
                        cs=116,
                        gold=6490,
                        damage_to_champions=7360,
                        result="LOSE",
                    ),
                ),
            ),
            TeamDetail(
                key="RED",
                win=True,
                kills=30,
                towers=3,
                dragons=1,
                barons=0,
                heralds=0,
                gold=36881,
                banned_champion_ids=(33, 117, 134, 164, 238),
                banned_champion_names=("Rammus", "Lulu", "Syndra", "Camille", "Zed"),
                participants=(
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival1",
                        tag_line="BR1",
                        champion_id=58,
                        champion_name="Renekton",
                        team_key="RED",
                        position="TOP",
                        items=(1055, 2031, 6692, 3111, 2021),
                        item_names=(
                            "Lâmina de Doran",
                            "Poção com Refil",
                            "Eclipse",
                            "Passos de Mercúrio",
                            "Tunelizador",
                        ),
                        spells=(4, 14),
                        primary_style_id=8000,
                        primary_rune_id=8010,
                        secondary_style_id=8400,
                        champion_level=13,
                        kills=7,
                        deaths=0,
                        assists=2,
                        cs=153,
                        gold=8471,
                        damage_to_champions=11033,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival2",
                        tag_line="BR1",
                        champion_id=81,
                        champion_name="Ezreal",
                        team_key="RED",
                        position="ADC",
                        items=(1086, 3078, 3133, 1036, 3070),
                        item_names=(
                            "Arco de Doran",
                            "Força da Trindade",
                            "Martelo de Guerra de Caulfield",
                            "Espada Longa",
                            "Lágrima da Deusa",
                        ),
                        spells=(7, 4),
                        primary_style_id=8000,
                        primary_rune_id=8005,
                        secondary_style_id=8300,
                        champion_level=11,
                        kills=7,
                        deaths=1,
                        assists=3,
                        cs=125,
                        gold=8035,
                        damage_to_champions=10519,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival3",
                        tag_line="BR1",
                        champion_id=526,
                        champion_name="Rell",
                        team_key="RED",
                        position="SUPPORT",
                        items=(3869, 3047, 3190, 1028, 1029, 1029),
                        item_names=(
                            "Oposição Celestial",
                            "Botas Galvanizadas de Aço",
                            "Medalhão dos Solari de Ferro",
                            "Cristal de Rubi",
                            "Couraça de Pano",
                            "Couraça de Pano",
                        ),
                        spells=(4, 14),
                        primary_style_id=8400,
                        primary_rune_id=8439,
                        secondary_style_id=8300,
                        champion_level=8,
                        kills=1,
                        deaths=5,
                        assists=15,
                        cs=20,
                        gold=5317,
                        damage_to_champions=5007,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival4",
                        tag_line="BR1",
                        champion_id=711,
                        champion_name="Vex",
                        team_key="RED",
                        position="MID",
                        items=(1056, 6655, 3175, 1058, 2055),
                        item_names=(
                            "Anel de Doran",
                            "Eco de Luden",
                            "Sapatos Enfeitiçados",
                            "Bastão Desnecessariamente Grande",
                            "Sentinela de Controle",
                        ),
                        spells=(4, 14),
                        primary_style_id=8100,
                        primary_rune_id=8112,
                        secondary_style_id=8200,
                        champion_level=11,
                        kills=8,
                        deaths=1,
                        assists=5,
                        cs=107,
                        gold=7420,
                        damage_to_champions=11181,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival5",
                        tag_line="BR1",
                        champion_id=234,
                        champion_name="Viego",
                        team_key="RED",
                        position="JUNGLE",
                        items=(6676, 6672, 1001, 1018),
                        item_names=("A Coletora", "Mata-Cráquens", "Botas", "Capa da Agilidade"),
                        spells=(11, 4),
                        primary_style_id=8100,
                        primary_rune_id=9923,
                        secondary_style_id=8000,
                        champion_level=11,
                        kills=7,
                        deaths=1,
                        assists=5,
                        cs=121,
                        gold=7638,
                        damage_to_champions=9061,
                        result="WIN",
                    ),
                ),
            ),
        ),
        average_tier="EMERALD",
    )
    tool, arguments = send.calls[0]
    assert tool == "lol_get_summoner_game_detail"
    assert arguments["game_id"] == "wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg="
    assert arguments["focus_riot_id"] == "Jogador#BR1"


def test_an_empty_response_means_no_game_detail():
    source = SummonerHistorySource(send=FakeSend(matches_answer=""))

    detail = source.fetch_game_detail(
        "id", datetime(2026, 8, 23, tzinfo=timezone.utc), "BR", "Jogador", "BR1"
    )

    assert detail is None


def test_a_network_failure_means_no_game_detail():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    detail = source.fetch_game_detail(
        "id", datetime(2026, 8, 23, tzinfo=timezone.utc), "BR", "Jogador", "BR1"
    )

    assert detail is None


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
