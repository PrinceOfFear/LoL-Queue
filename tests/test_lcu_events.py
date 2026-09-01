"""Assinatura WAMP da LCU: s\u00f3 eventos JSON v\u00e1lidos chegam ao consumidor."""

from __future__ import annotations

import json

from lolqueue.core.lp_history import LpChangeTracker, LpHistory
from lolqueue.lcu import endpoints
from lolqueue.lcu.credentials import Credentials
from lolqueue.lcu.events import (
    JSON_API_TOPIC,
    LcuJsonApiEvents,
    decode_json_api_event,
    subscription_message,
)
from tests.fakes import FakeLcuClient


def test_decodes_only_the_expected_wamp_json_api_event():
    event = {
        "uri": "/lol-ranked/v1/current-lp-change-notification",
        "eventType": "Update",
        "data": {"leagueNotifications": []},
    }

    assert decode_json_api_event(json.dumps([8, JSON_API_TOPIC, event])) == event
    assert decode_json_api_event([8, "another-topic", event]) is None
    assert decode_json_api_event([5, JSON_API_TOPIC]) is None
    assert decode_json_api_event("not json") is None


def test_subscription_message_uses_the_lcu_wamp_topic():
    assert json.loads(subscription_message()) == [5, JSON_API_TOPIC]


class _Socket:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.sent = []
        self.closed = False

    def recv(self, timeout=None):
        return next(self._messages)

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


def test_listener_waits_for_welcome_then_forwards_events():
    received = []
    event = {"uri": "/wanted", "eventType": "Update", "data": {"ok": True}}
    socket = _Socket(
        [
            json.dumps([0, "session", 1, "wamp"]),
            json.dumps([8, JSON_API_TOPIC, event]),
        ]
    )
    listener = None

    def on_event(value):
        received.append(value)
        listener._stopped.set()

    listener = LcuJsonApiEvents(
        credentials=object(),
        on_event=on_event,
        connection_factory=lambda _credentials: socket,
    )

    listener._listen(socket)

    assert received == [event]
    assert [json.loads(message) for message in socket.sent] == [
        [5, JSON_API_TOPIC]
    ]


def _lp_notification(**changes):
    payload = {
        "notifyReason": "LEAGUE_POINTS_UPDATE",
        "changeReason": "GAME_END",
        "queueId": 420,
        "gameId": 1234,
        "leaguePointsDelta": 22,
        "leaguePoints": 61,
        "tier": "GOLD",
        "rank": "II",
    }
    payload.update(changes)
    return payload


def test_tracker_records_only_the_targeted_live_pdl_event(tmp_path):
    history = LpHistory(tmp_path / "pdl.json")
    captured = []
    tracker = LpChangeTracker(FakeLcuClient(), history, on_change=captured.append)

    tracker.handle_lcu_event(
        {
            "uri": endpoints.CURRENT_LP_CHANGE_NOTIFICATION,
            "eventType": "Update",
            "data": {"leagueNotifications": [_lp_notification()]},
        }
    )
    tracker.handle_lcu_event(
        {
            "uri": "/lol-summoner/v1/current-summoner",
            "eventType": "Update",
            "data": {"leagueNotifications": [_lp_notification(gameId=9999)]},
        }
    )

    assert history.change_for(1234).delta == 22
    assert history.change_for(9999) is None
    assert [change.game_id for change in captured] == [1234]


class _ListenerSpy:
    def __init__(self, credentials, callback):
        self.credentials = credentials
        self.callback = callback
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class _ClientWithCredentials(FakeLcuClient):
    credentials = Credentials(port=12345, token="test-token")


def test_tracker_starts_and_stops_the_live_listener_once(tmp_path):
    made = []

    def make_listener(credentials, callback):
        listener = _ListenerSpy(credentials, callback)
        made.append(listener)
        return listener

    tracker = LpChangeTracker(
        _ClientWithCredentials(),
        LpHistory(tmp_path / "pdl.json"),
        event_listener_factory=make_listener,
    )

    tracker.start_live_events()
    tracker.start_live_events()
    tracker.stop()

    assert len(made) == 1
    assert made[0].credentials.port == 12345
    assert made[0].started == 1
    assert made[0].stopped == 1
