"""A ativacao nunca aceita HTTP, proxy herdado ou redirecionamento."""

from __future__ import annotations

import pytest

from lolqueue.licenca import cliente


def test_license_server_requires_clean_https_url(monkeypatch):
    monkeypatch.setattr(cliente.embutido, "servidor", lambda: "http://example.invalid")
    with pytest.raises(cliente.ErroDeRede, match="insegura"):
        cliente._url("/api/saude")

    monkeypatch.setattr(
        cliente.embutido,
        "servidor",
        lambda: "https://licencas.example.invalid/base",
    )
    assert cliente._url("/api/saude") == "https://licencas.example.invalid/base/api/saude"


def test_license_session_does_not_inherit_proxy_or_netrc():
    session = cliente._session()
    assert session.trust_env is False


class _Response:
    status_code = 302

    def json(self):
        return {}


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Response()


def test_license_redirect_is_not_followed(monkeypatch):
    session = _Session()
    monkeypatch.setattr(cliente, "_session", lambda: session)
    monkeypatch.setattr(cliente.embutido, "servidor", lambda: "https://licencas.example.invalid")

    with pytest.raises(cliente.ErroDeRede, match="redirecionar"):
        cliente._falar("/api/ativar", {"chave": "LQ-TEST"})
    assert session.calls[0][1]["allow_redirects"] is False


def test_checkout_url_uses_the_same_validated_https_server(monkeypatch):
    monkeypatch.setattr(
        cliente.embutido,
        "servidor",
        lambda: "https://licencas.example.invalid/base",
    )
    assert cliente.checkout_url() == "https://licencas.example.invalid/base/checkout"
