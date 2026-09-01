import pytest
import requests

from lolqueue.lcu.client import ClientClosed, LcuClient, LcuError
from lolqueue.lcu.credentials import Credentials

CREDS = Credentials(port=52847, token="tok")


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", payload=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, raises=None):
        self.auth = None
        self.verify = None
        self.calls = []
        self._response = response
        self._raises = raises

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self._raises is not None:
            raise self._raises
        return self._response


def test_sends_basic_auth_as_user_riot():
    session = FakeSession(FakeResponse(payload={"ok": True}))
    LcuClient(CREDS, session=session)
    assert session.auth == ("riot", "tok")
    assert session.verify is False
    assert session.trust_env is False


def test_get_returns_parsed_json():
    session = FakeSession(FakeResponse(payload={"phase": "Lobby"}))
    client = LcuClient(CREDS, session=session)
    assert client.get("/x") == {"phase": "Lobby"}


def test_builds_loopback_url():
    session = FakeSession(FakeResponse())
    LcuClient(CREDS, session=session).get("/lol-gameflow/v1/gameflow-phase")
    method, url, _ = session.calls[0]
    assert method == "GET"
    assert url == "https://127.0.0.1:52847/lol-gameflow/v1/gameflow-phase"
    assert session.calls[0][2]["allow_redirects"] is False


def test_rejects_redirects_and_non_local_paths():
    redirect = FakeSession(FakeResponse(status_code=302))
    with pytest.raises(LcuError, match="redirecionar"):
        LcuClient(CREDS, session=redirect).get("/x")

    session = FakeSession(FakeResponse())
    with pytest.raises(LcuError, match="caminho"):
        LcuClient(CREDS, session=session).get("https://example.invalid/")
    assert session.calls == []


def test_empty_body_returns_none():
    session = FakeSession(FakeResponse(content=b""))
    assert LcuClient(CREDS, session=session).post("/x") is None


def test_connection_refused_means_client_closed():
    session = FakeSession(raises=requests.exceptions.ConnectionError())
    with pytest.raises(ClientClosed):
        LcuClient(CREDS, session=session).get("/x")


def test_timeout_is_an_lcu_error_not_client_closed():
    session = FakeSession(raises=requests.exceptions.Timeout())
    client = LcuClient(CREDS, session=session)
    with pytest.raises(LcuError) as excinfo:
        client.get("/x")
    assert not isinstance(excinfo.value, ClientClosed)


def test_raw_returns_bytes_without_parsing_json():
    """Retratos de campeão são PNG: passar por .json() estouraria."""
    session = FakeSession(FakeResponse(content=b"\x89PNG\r\n"))
    assert LcuClient(CREDS, session=session).raw("/icon.png") == b"\x89PNG\r\n"


def test_raw_raises_on_http_error_like_the_rest():
    session = FakeSession(FakeResponse(status_code=404, content=b"nope"))
    with pytest.raises(LcuError):
        LcuClient(CREDS, session=session).raw("/icon.png")


def test_http_error_status_raises_lcu_error():
    session = FakeSession(FakeResponse(status_code=404))
    with pytest.raises(LcuError):
        LcuClient(CREDS, session=session).get("/x")
