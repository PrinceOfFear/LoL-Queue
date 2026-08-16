from lolqueue.lcu import credentials
from lolqueue.lcu.credentials import Credentials, parse_lockfile


def test_parses_well_formed_lockfile():
    creds = parse_lockfile("LeagueClient:26536:52847:Ab3xYz-token_9:https")
    assert creds == Credentials(port=52847, token="Ab3xYz-token_9")


def test_base_url_points_at_loopback():
    assert Credentials(port=52847, token="x").base_url == "https://127.0.0.1:52847"


def test_tolerates_trailing_whitespace():
    creds = parse_lockfile("LeagueClient:1:443:tok:https\n")
    assert creds is not None
    assert creds.port == 443


def test_rejects_malformed_lockfile():
    assert parse_lockfile("garbage") is None
    assert parse_lockfile("") is None
    assert parse_lockfile("LeagueClient:26536:notaport:tok:https") is None
    assert parse_lockfile("LeagueClient:26536:52847") is None


class FakeProcess:
    def __init__(self, argv):
        self._argv = argv

    def cmdline(self):
        return self._argv


def test_reads_credentials_from_process_command_line(monkeypatch):
    process = FakeProcess(
        [
            r"C:\Riot Games\League of Legends\LeagueClientUx.exe",
            "--app-port=51234",
            "--remoting-auth-token=abc-123",
        ]
    )
    monkeypatch.setattr(credentials, "_client_process", lambda: process)
    assert credentials.credentials_from_process() == Credentials(
        port=51234, token="abc-123"
    )


def test_process_without_the_expected_flags_yields_nothing(monkeypatch):
    process = FakeProcess(["LeagueClientUx.exe", "--unrelated=1"])
    monkeypatch.setattr(credentials, "_client_process", lambda: process)
    assert credentials.credentials_from_process() is None


def test_client_closed_is_not_an_error(monkeypatch):
    monkeypatch.setattr(credentials, "_client_process", lambda: None)
    monkeypatch.setattr(credentials, "credentials_from_lockfile", lambda: None)
    assert credentials.discover() is None
