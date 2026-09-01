"""PDL do histórico: só o que o cliente confirmou para cada partida."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from lolqueue.core.lp_history import (
    LP_SOURCE_LOCAL_SNAPSHOT,
    LP_SOURCE_MANUAL,
    LpChange,
    LpChangeTracker,
    LpHistory,
    ManualLpInput,
    format_lp_delta,
    parse_lp_changes,
)
from lolqueue.core.summoner_history import MatchSummary
from lolqueue.lcu import endpoints
from lolqueue.lcu.client import ClientClosed
from tests.fakes import FakeLcuClient


def _notification(**changes):
    base = {
        "notifyReason": "LEAGUE_POINTS_UPDATE",
        "changeReason": "GAME_END",
        "queueId": 420,
        "gameId": 998877,
        "leaguePointsDelta": 21,
        "leaguePoints": 29,
        "tier": "GOLD",
        "rank": "IV",
    }
    base.update(changes)
    return base


def _match(**changes) -> MatchSummary:
    base = {
        "match_id": "opgg-opaque-id",
        "champion_id": 54,
        "champion_name": "Malphite",
        "result": "WIN",
        "kills": 4,
        "deaths": 2,
        "assists": 7,
        "cs": 188,
        "duration_seconds": 958,
        "queue_type": "SOLORANKED",
        "position": "TOP",
        # Esta é a hora de término: 11:44:49 + 958 segundos.
        "played_at": datetime(2026, 8, 23, 12, 0, 47, tzinfo=timezone.utc),
        "items": (1001,),
        "item_names": ("Botas",),
        "spells": (4, 12),
        "primary_style_id": 8200,
        "primary_rune_id": 8229,
        "secondary_style_id": 8400,
        "champion_level": 14,
        "gold": 9812,
    }
    base.update(changes)
    return MatchSummary(**base)


def _local_client(notification=None) -> FakeLcuClient:
    puuid = "player-puuid"
    history_path = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)
    history_path_100 = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=100)
    history = {
        "games": {
            "games": [
                {
                    "gameId": 998877,
                    "queueId": 420,
                    "gameCreationDate": "2026-08-23T11:44:49Z",
                    "gameDuration": 958,
                    # A LCU não promete que o invocador logado será o
                    # primeiro. O jogador daqui é o participantId 2.
                    "participantIdentities": [
                        {"participantId": 1, "player": {"puuid": "other-player"}},
                        {"participantId": 2, "player": {"puuid": puuid}},
                    ],
                    "participants": [
                        {"participantId": 1, "championId": 22},
                        {"participantId": 2, "championId": 54},
                    ],
                }
            ]
        }
    }
    responses = {
        endpoints.CURRENT_SUMMONER: {"puuid": puuid},
        history_path: history,
        history_path_100: history,
    }
    if notification is not None:
        responses[endpoints.CURRENT_LP_CHANGE_NOTIFICATION] = {
            "leagueNotifications": [notification]
        }
    return FakeLcuClient(responses=responses)


def _ranked_stats(*, lp=41, wins=12, losses=9, tier="GOLD", division="IV"):
    return {
        "queues": [
            {
                "queueType": "RANKED_SOLO_5X5",
                "queueId": 420,
                "leaguePoints": lp,
                "wins": wins,
                "losses": losses,
                "tier": tier,
                "division": division,
            }
        ]
    }


def _ranked_games(*rows):
    return {"games": {"games": [{"gameId": game_id, "queueId": queue_id} for game_id, queue_id in rows]}}


def _snapshot_client(*, games=((1001, 420),), **rank):
    puuid = "snapshot-player"
    history_path = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)
    return FakeLcuClient(
        responses={
            endpoints.GAMEFLOW_SESSION: {"gameData": {"queue": {"id": 420}}},
            endpoints.CURRENT_SUMMONER: {"puuid": puuid},
            endpoints.CURRENT_RANKED_STATS: _ranked_stats(**rank),
            history_path: _ranked_games(*games),
            endpoints.CURRENT_LP_CHANGE_NOTIFICATION: {"leagueNotifications": []},
        }
    )


def test_parse_lp_change_reads_the_game_end_notification():
    changes = parse_lp_changes({"leagueNotifications": [_notification()]})

    assert changes == (
        LpChange(
            game_id=998877,
            queue_id=420,
            delta=21,
            league_points=29,
            tier="GOLD",
            division="IV",
        ),
    )


@pytest.mark.parametrize("notify_reason", ("LEAGUE_PROMOTED", "LEAGUE_DEMOTED"))
def test_parse_lp_change_reads_official_promotion_and_demotion_events(notify_reason):
    changes = parse_lp_changes(
        {"leagueNotifications": [_notification(notifyReason=notify_reason)]}
    )

    assert changes == (
        LpChange(
            game_id=998877,
            queue_id=420,
            delta=21,
            league_points=29,
            tier="GOLD",
            division="IV",
        ),
    )


def test_parse_lp_change_rejects_non_ranked_and_non_game_end_events():
    payload = {
        "leagueNotifications": [
            _notification(queueId=450),
            _notification(changeReason="SEASON_START"),
            _notification(notifyReason="SOMETHING_ELSE"),
        ]
    }

    assert parse_lp_changes(payload) == ()


def test_parse_lp_change_requires_the_official_game_end_envelope():
    raw_without_event_metadata = _notification()
    raw_without_event_metadata.pop("changeReason")
    raw_without_event_metadata.pop("notifyReason")

    assert parse_lp_changes(raw_without_event_metadata) == ()


def test_lp_values_are_persisted_and_only_applied_to_the_matching_game(tmp_path):
    path = tmp_path / "pdl.json"
    history = LpHistory(path)
    history.record_many(parse_lp_changes({"leagueNotifications": [_notification()]}))

    reopened = LpHistory(path)
    assert reopened.change_for(998877) is not None

    enriched = reopened.enrich_matches(_local_client(), (_match(),), import_logs=False)
    assert enriched[0].lp_delta == 21
    assert enriched[0].lp_after == 29
    assert enriched[0].lp_queue == "SOLORANKED"

    unrelated = reopened.enrich_matches(
        _local_client(), (_match(champion_id=22),), import_logs=False
    )
    assert unrelated[0].lp_delta is None


def test_manual_import_validates_the_exact_local_game_and_persists_its_origin(tmp_path):
    path = tmp_path / "pdl.json"
    history = LpHistory(path)
    match = _match()

    result = history.import_manual(
        _local_client(),
        (
            ManualLpInput(
                game_id=998877,
                queue_id=420,
                champion_id=54,
                ended_at=match.played_at,
                delta=-18,
            ),
        ),
    )

    assert result.rejected == 0
    assert [change.delta for change in result.imported] == [-18]
    reopened = LpHistory(path)
    change = reopened.change_for(998877)
    assert change is not None
    assert change.source == LP_SOURCE_MANUAL
    enriched = reopened.enrich_matches(_local_client(), (match,), import_logs=False)
    assert enriched[0].lp_delta == -18
    assert enriched[0].lp_source == LP_SOURCE_MANUAL
    assert enriched[0].local_game_id == 998877


def test_manual_import_rejects_everything_that_does_not_prove_the_same_game(tmp_path):
    history = LpHistory(tmp_path / "pdl.json")
    match = _match()

    for row in (
        # Campeão divergente.
        ManualLpInput(998877, 420, 22, match.played_at, 22),
        # Horário fora da janela estrita de associação.
        ManualLpInput(998877, 420, 54, match.played_at + timedelta(minutes=3), 22),
        # Um id de partida que não pertence à conta aberta.
        ManualLpInput(123456, 420, 54, match.played_at, 22),
    ):
        result = history.import_manual(_local_client(), (row,))
        assert result.imported == ()
        assert result.rejected == 1
    assert history.change_for(998877) is None


def test_manual_import_never_overwrites_a_riot_confirmation(tmp_path):
    history = LpHistory(tmp_path / "pdl.json")
    match = _match()
    history.record_many(parse_lp_changes({"leagueNotifications": [_notification()]}))

    result = history.import_manual(
        _local_client(),
        (
            ManualLpInput(998877, 420, 54, match.played_at, -18),
        ),
    )

    assert result.imported == ()
    assert result.rejected == 1
    assert history.change_for(998877).delta == 21


def test_riot_confirmation_replaces_an_earlier_manual_import(tmp_path):
    history = LpHistory(tmp_path / "pdl.json")
    match = _match()
    history.import_manual(
        _local_client(),
        (ManualLpInput(998877, 420, 54, match.played_at, -18),),
    )

    history.record_many(parse_lp_changes({"leagueNotifications": [_notification()]}))

    change = history.change_for(998877)
    assert change is not None
    assert change.delta == 21
    assert change.source != LP_SOURCE_MANUAL


def test_ambiguous_local_match_is_not_enriched_or_offered_for_import(tmp_path):
    client = _local_client()
    puuid = "player-puuid"
    history_path = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)
    duplicate = dict(client.responses[history_path]["games"]["games"][0])
    duplicate["gameId"] = 998878
    client.responses[history_path] = {
        "games": {"games": [client.responses[history_path]["games"]["games"][0], duplicate]}
    }
    client.responses[endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=100)] = client.responses[
        history_path
    ]
    history = LpHistory(tmp_path / "pdl.json")
    enriched = history.enrich_matches(client, (_match(),), import_logs=False)

    assert enriched[0].local_game_id is None


def test_trace_log_import_recovers_a_recent_official_notification(tmp_path):
    payload = {"leagueNotifications": [_notification(gameId=12345, leaguePointsDelta=-18)]}
    trace = tmp_path / "2026-08-31_LeagueClient-tracing.json"
    trace.write_text(json.dumps({"dds": json.dumps(payload)}) + "\n", encoding="utf-8")

    history = LpHistory(tmp_path / "pdl.json")
    received = history.import_trace_logs(tmp_path)

    assert [change.game_id for change in received] == [12345]
    assert history.change_for(12345).delta == -18
    assert history.import_trace_logs(tmp_path) == ()


def test_trace_log_import_reads_the_current_complete_trace_document(tmp_path):
    """O cliente atual guarda cada DDS dentro de ``entries``, não por linha."""

    payload = {
        "header": {"version": 1},
        "entries": [
            {"dds": json.dumps({"leagueNotifications": [_notification(gameId=45678)]})},
            {"dds": json.dumps({"leagueNotifications": [_notification(gameId=45679, leaguePointsDelta=-19)]})},
        ],
    }
    trace = tmp_path / "2026-08-31_LeagueClient-tracing.json"
    trace.write_text(json.dumps(payload), encoding="utf-8")

    history = LpHistory(tmp_path / "pdl.json")
    received = history.import_trace_logs(tmp_path)

    assert [(change.game_id, change.delta) for change in received] == [
        (45678, 21),
        (45679, -19),
    ]


def test_tracker_captures_the_value_after_a_game_even_if_automation_is_off(
    tmp_path, monkeypatch
):
    clock = [100.0]
    captured = []
    history = LpHistory(tmp_path / "pdl.json")
    client = _local_client(_notification())
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(
        client,
        history,
        on_change=captured.append,
        now=lambda: clock[0],
    )

    tracker.handle_phase("EndOfGame")
    tracker.tick()
    tracker.tick()

    assert history.change_for(998877).delta == 21
    assert captured == [history.change_for(998877)]
    assert client.paths("GET").count(endpoints.CURRENT_LP_CHANGE_NOTIFICATION) == 1


def test_tracker_catches_a_still_live_notification_when_opened_in_the_lobby(
    tmp_path, monkeypatch
):
    """O app pode iniciar depois de a fase EndOfGame ter passado."""

    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    client = _local_client(_notification())
    tracker = LpChangeTracker(client, history, now=lambda: clock[0])

    tracker.tick()
    clock[0] = 4.9
    tracker.tick()
    clock[0] = 5.0
    tracker.tick()

    assert history.change_for(998877).delta == 21
    assert client.paths("GET").count(endpoints.CURRENT_LP_CHANGE_NOTIFICATION) == 2


class _SequencedLpClient(FakeLcuClient):
    def __init__(self, payloads):
        super().__init__()
        self._payloads = list(payloads)

    def get(self, path):
        if path == endpoints.CURRENT_LP_CHANGE_NOTIFICATION:
            self._record("GET", path)
            return self._payloads.pop(0) if self._payloads else {"leagueNotifications": []}
        return super().get(path)


def test_tracker_keeps_polling_when_an_older_notification_arrives_first(
    tmp_path, monkeypatch
):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    client = _SequencedLpClient(
        [
            {"leagueNotifications": [_notification(gameId=111, leaguePointsDelta=-16)]},
            {"leagueNotifications": [_notification(gameId=222, leaguePointsDelta=22)]},
        ]
    )
    captured = []
    tracker = LpChangeTracker(client, history, captured.append, now=lambda: clock[0])

    tracker.handle_phase("EndOfGame")
    tracker.tick()
    clock[0] = 1.0
    tracker.tick()

    assert [change.game_id for change in captured] == [111, 222]
    assert history.change_for(222).delta == 22
    assert client.paths("GET").count(endpoints.CURRENT_LP_CHANGE_NOTIFICATION) == 2


def test_tracker_keeps_the_capture_window_during_the_next_champ_select(
    tmp_path, monkeypatch
):
    """O cliente pode publicar o PDL enquanto a próxima seleção já abriu."""

    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(
        _SequencedLpClient([{"leagueNotifications": [_notification()]}]),
        history,
        now=lambda: clock[0],
    )

    tracker.handle_phase("EndOfGame")
    tracker.handle_phase("ChampSelect")
    tracker.tick()

    assert history.change_for(998877).delta == 21


def test_tracker_allows_client_close_to_reach_the_watcher(tmp_path, monkeypatch):
    history = LpHistory(tmp_path / "pdl.json")
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(FakeLcuClient(closed=True), history, now=lambda: 0.0)

    tracker.handle_phase("EndOfGame")

    with pytest.raises(ClientClosed):
        tracker.tick()


def test_snapshot_fallback_binds_an_exact_delta_to_the_new_local_game(tmp_path, monkeypatch):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    client = _snapshot_client(lp=41, wins=12, losses=9)
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    captured = []
    tracker = LpChangeTracker(client, history, captured.append, now=lambda: clock[0])

    tracker.handle_phase("InProgress")
    snapshot = history.pending_snapshot()
    assert snapshot is not None
    assert snapshot.queue_id == 420

    puuid = "snapshot-player"
    history_path = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)
    client.responses[endpoints.CURRENT_RANKED_STATS] = _ranked_stats(
        lp=63, wins=13, losses=9
    )
    client.responses[history_path] = _ranked_games((2002, 420), (1001, 420))

    tracker.handle_phase("EndOfGame")
    clock[0] = 6.0
    tracker.tick()

    assert history.change_for(2002) == LpChange(
        game_id=2002,
        queue_id=420,
        delta=22,
        league_points=63,
        tier="GOLD",
        division="IV",
        source=LP_SOURCE_LOCAL_SNAPSHOT,
    )
    assert captured == [history.change_for(2002)]
    assert history.pending_snapshot() is None


def test_snapshot_fallback_survives_restart_and_resolves_from_lobby(tmp_path, monkeypatch):
    path = tmp_path / "pdl.json"
    before = LpHistory(path)
    client = _snapshot_client(lp=41, wins=12, losses=9)
    tracker = LpChangeTracker(client, before, now=lambda: 0.0)

    assert tracker.capture_current_game() is True
    assert LpHistory(path).pending_snapshot() is not None

    puuid = "snapshot-player"
    history_path = endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)
    client.responses[endpoints.CURRENT_RANKED_STATS] = _ranked_stats(
        lp=59, wins=12, losses=10
    )
    client.responses[history_path] = _ranked_games((2002, 420), (1001, 420))
    after = LpHistory(path)
    monkeypatch.setattr(after, "import_trace_logs", lambda: ())
    resumed = LpChangeTracker(client, after, now=lambda: 10.0)

    # Nenhuma fase de fim foi vista por esta execuÃ§Ã£o: o snapshot salvo
    # ainda assim sÃ³ Ã© resolvido quando todos os sinais concordam.
    resumed.handle_phase("Lobby")
    resumed.tick()

    assert after.change_for(2002).delta == 18
    assert after.pending_snapshot() is None


def test_snapshot_fallback_records_an_observed_zero_delta(tmp_path, monkeypatch):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    client = _snapshot_client(lp=41, wins=12, losses=9)
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(client, history, now=lambda: clock[0])
    tracker.handle_phase("InProgress")
    puuid = "snapshot-player"
    client.responses[endpoints.CURRENT_RANKED_STATS] = _ranked_stats(
        lp=41, wins=12, losses=10
    )
    client.responses[endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)] = _ranked_games(
        (2002, 420), (1001, 420)
    )

    tracker.handle_phase("EndOfGame")
    clock[0] = 6.0
    tracker.tick()

    assert history.change_for(2002).delta == 0
    assert history.pending_snapshot() is None


@pytest.mark.parametrize(
    ("after_rank", "after_games"),
    [
        # Duas linhas novas nÃ£o dizem qual delas causou a mudanÃ§a.
        (_ranked_stats(lp=60, wins=13, losses=9), ((2002, 420), (2003, 420), (1001, 420))),
        # Outra fila nÃ£o pode usar o PDL da Solo.
        (_ranked_stats(lp=60, wins=13, losses=9), ((2002, 440), (1001, 420))),
        # PromoÃ§Ã£o/rebaixamento exige o envelope oficial.
        (_ranked_stats(lp=60, wins=13, losses=9, tier="PLATINUM"), ((2002, 420), (1001, 420))),
        # Sem uma nova vitÃ³ria ou derrota, o retrato ainda nÃ£o fechou.
        (_ranked_stats(lp=60, wins=12, losses=9), ((2002, 420), (1001, 420))),
    ],
)
def test_snapshot_fallback_refuses_every_ambiguous_or_rank_transition_case(
    tmp_path, monkeypatch, after_rank, after_games
):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    client = _snapshot_client(lp=41, wins=12, losses=9)
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(client, history, now=lambda: clock[0])
    tracker.handle_phase("InProgress")
    puuid = "snapshot-player"
    client.responses[endpoints.CURRENT_RANKED_STATS] = after_rank
    client.responses[endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)] = _ranked_games(
        *after_games
    )

    tracker.handle_phase("EndOfGame")
    clock[0] = 6.0
    tracker.tick()

    assert history.change_for(2002) is None
    assert history.pending_snapshot() is not None


def test_snapshot_fallback_never_joins_two_accounts(tmp_path, monkeypatch):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    client = _snapshot_client(lp=41, wins=12, losses=9)
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(client, history, now=lambda: clock[0])
    tracker.handle_phase("InProgress")
    client.responses[endpoints.CURRENT_SUMMONER] = {"puuid": "other-account"}
    client.responses[endpoints.CURRENT_RANKED_STATS] = _ranked_stats(
        lp=63, wins=13, losses=9
    )
    client.responses[endpoints.MATCH_HISTORY.format(puuid="other-account", end_index=20)] = _ranked_games(
        (2002, 420), (1001, 420)
    )

    tracker.handle_phase("EndOfGame")
    clock[0] = 6.0
    tracker.tick()

    assert history.change_for(2002) is None
    assert history.pending_snapshot() is not None


def test_official_notification_wins_over_snapshot_fallback(tmp_path, monkeypatch):
    clock = [0.0]
    history = LpHistory(tmp_path / "pdl.json")
    client = _snapshot_client(lp=41, wins=12, losses=9)
    monkeypatch.setattr(history, "import_trace_logs", lambda: ())
    tracker = LpChangeTracker(client, history, now=lambda: clock[0])
    tracker.handle_phase("InProgress")
    puuid = "snapshot-player"
    client.responses[endpoints.CURRENT_RANKED_STATS] = _ranked_stats(
        lp=63, wins=13, losses=9
    )
    client.responses[endpoints.MATCH_HISTORY.format(puuid=puuid, end_index=20)] = _ranked_games(
        (2002, 420), (1001, 420)
    )
    client.responses[endpoints.CURRENT_LP_CHANGE_NOTIFICATION] = {
        "leagueNotifications": [_notification(gameId=2002, leaguePointsDelta=19)]
    }

    tracker.handle_phase("EndOfGame")
    clock[0] = 6.0
    tracker.tick()

    assert history.change_for(2002).delta == 19
    assert history.pending_snapshot() is None


def test_lp_format_makes_gain_loss_and_neutral_unambiguous():
    assert format_lp_delta(21) == "+21 PDL"
    assert format_lp_delta(-18) == "−18 PDL"
    assert format_lp_delta(0) == "±0 PDL"
