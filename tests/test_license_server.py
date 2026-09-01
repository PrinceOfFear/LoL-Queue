from __future__ import annotations

import time
from dataclasses import replace

from fastapi.testclient import TestClient

from lolqueue.licenca import chave
from servidor.app import create_app
from servidor.config import Settings
from servidor.db import LicenseStore


def _setup(tmp_path):
    private, public = chave.gerar_par()
    settings = Settings(
        database=tmp_path / "licencas.db",
        private_key=private,
        webhook_token="picpay-webhook-test-token",
        picpay_client_id="client",
        picpay_client_secret="secret",
        picpay_plan_id="plan",
    )
    app = create_app(settings)
    return settings, public, LicenseStore(settings.database), TestClient(app)


def test_health_does_not_expose_secrets(tmp_path):
    _settings, _public, _store, client = _setup(tmp_path)
    response = client.get("/api/saude")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "servico": "lolqueue-license",
        "plano": "mensal",
        "moeda": "BRL",
        "preco_centavos": 2000,
    }
    assert "secret" not in response.text


def test_activation_is_bound_to_one_machine_and_signed(tmp_path):
    settings, public, store, client = _setup(tmp_path)
    key = "LQ-ABCD-EFGH-JKLM"
    machine = "a" * 32
    store.provision(key, paid_until=int(time.time()) + 86400, now="now")

    response = client.post(
        "/api/ativar",
        json={"chave": key.lower(), "maquina": machine, "apelido": "PC", "versao": "0.2.1"},
    )
    assert response.status_code == 200
    ticket = response.json()["bilhete"]
    checked = chave.conferir(ticket, public, maquina=machine)
    assert checked.chave == key
    assert client.post("/api/ativar", json={"chave": key, "maquina": "b" * 32}).status_code == 409
    assert settings.private_key not in response.text


def test_expired_activation_does_not_bind_machine(tmp_path):
    _settings, _public, store, client = _setup(tmp_path)
    key = "LQ-ABCD-EFGH-JKLM"
    store.provision(key, paid_until=int(time.time()) - 1, now="now")
    response = client.post("/api/ativar", json={"chave": key, "maquina": "a" * 32})
    assert response.status_code == 403
    assert store.find(key)["machine"] is None


def test_picpay_webhook_is_authenticated_idempotent_and_extends_month(tmp_path):
    settings, _public, store, client = _setup(tmp_path)
    key = "LQ-NOPQ-RSTU-VWXY"
    subscription = "subscription-test-1"
    before = int(time.time()) + 86400
    store.provision(key, paid_until=before, provider_subscription_id=subscription, now="now")
    payload = {
        "id": "event-1",
        "type": "PAYMENT",
        "data": {
            "status": "PAID",
            "amount": settings.price_cents,
            "merchantSubscriptionId": subscription,
            "merchantChargeId": "charge-1",
        },
    }
    denied = client.post("/webhooks/picpay", json=payload)
    assert denied.status_code == 401
    accepted = client.post(
        "/webhooks/picpay",
        headers={"Authorization": settings.webhook_token},
        json=payload,
    )
    assert accepted.status_code == 200
    row = store.find_by_provider_id(subscription)
    assert row is not None and row["status"] == "active"
    assert row["paid_until"] > before
    duplicate = client.post(
        "/webhooks/picpay",
        headers={"Authorization": settings.webhook_token},
        json=payload,
    )
    assert duplicate.status_code == 200
    assert store.find_by_provider_id(subscription)["paid_until"] == row["paid_until"]


def test_subscription_endpoint_never_accepts_raw_card_data(tmp_path, monkeypatch):
    import servidor.app as module

    settings, _public, store, client = _setup(tmp_path)
    calls = []

    class FakePicPay:
        def __init__(self, *args):
            calls.append(args)

        def create_subscription(self, **kwargs):
            calls.append(kwargs)
            return {"id": "provider-id"}

    monkeypatch.setattr(module, "PicPayClient", FakePicPay)
    response = client.post(
        "/api/assinaturas",
        json={
            "name": "Thiago",
            "email": "thiago@example.com",
            "document_type": "CPF",
            "document": "12345678901",
            "phone": {"country_code": "55", "area_code": "11", "number": "999999999", "type": "MOBILE"},
            "card_token": "temporary-token",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"].startswith("aguardando")
    assert store.find(response.json()["chave"])["paid_until"] == 0
    assert calls[-1]["temporary_card_token"] == "temporary-token"

    raw_card = {
        "name": "Thiago",
        "email": "thiago@example.com",
        "document_type": "CPF",
        "document": "12345678901",
        "phone": {"country_code": "55", "area_code": "11", "number": "999999999", "type": "MOBILE"},
        "card_token": "temporary-token",
        "card_number": "4111111111111111",
    }
    rejected = client.post("/api/assinaturas", json=raw_card)
    assert rejected.status_code == 422


def test_checkout_page_is_configured_with_nonce_and_never_exposes_backend_secret(tmp_path):
    settings, _public, _store, _client = _setup(tmp_path)
    settings = replace(
        settings,
        picpay_merchant_credential="12345678901234",
        picpay_transparent_token="front-token",
        checkout_api_base_url="https://licencas.example.invalid",
    )
    client = TestClient(create_app(settings))
    response = client.get("/checkout")
    assert response.status_code == 200
    assert "checkout.picpay.com/cdn/pp-transparent" in response.text
    assert "front-token" in response.text
    assert settings.picpay_client_secret not in response.text
    csp = response.headers["content-security-policy"]
    assert "'nonce-" in csp
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0]


def test_external_checkout_cors_allows_only_configured_origin(tmp_path):
    settings, _public, _store, _client = _setup(tmp_path)
    settings = replace(
        settings,
        picpay_merchant_credential="12345678901234",
        picpay_transparent_token="front-token",
        checkout_api_base_url="https://licencas.example.invalid",
        checkout_allowed_origins=("https://pagamento.example.invalid",),
    )
    client = TestClient(create_app(settings))
    allowed = client.options(
        "/api/assinaturas",
        headers={
            "Origin": "https://pagamento.example.invalid",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://pagamento.example.invalid"
    denied = client.options(
        "/api/assinaturas",
        headers={
            "Origin": "https://outro.example.invalid",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_checkout_is_not_available_without_frontend_picpay_credentials(tmp_path):
    _settings, _public, _store, client = _setup(tmp_path)
    response = client.get("/checkout")
    assert response.status_code == 503


def test_webhook_rejects_non_transaction_event(tmp_path):
    settings, _public, store, client = _setup(tmp_path)
    key = "LQ-NOPQ-RSTU-VWXY"
    store.provision(
        key,
        paid_until=int(time.time()),
        provider_subscription_id="subscription-test-2",
        now="now",
    )
    payload = {
        "id": "event-3",
        "data": {
            "status": "PAID",
            "amount": settings.price_cents,
            "merchantSubscriptionId": "subscription-test-2",
        },
    }
    response = client.post(
        "/webhooks/picpay",
        headers={
            "Authorization": settings.webhook_token,
            "event-type": "Challenge3dsUpdateMessage",
        },
        json=payload,
    )
    assert response.status_code == 400


def test_webhook_can_match_picpay_charge_id_when_subscription_id_is_omitted(tmp_path):
    settings, _public, store, client = _setup(tmp_path)
    key = "LQ-ABCD-EFGH-JKLM"
    store.provision(
        key,
        paid_until=int(time.time()),
        provider_subscription_id="subscription-test-3",
        provider_charge_id="charge-test-3",
        now="now",
    )
    payload = {
        "id": "event-charge-only",
        "data": {
            "status": "PAID",
            "amount": settings.price_cents,
            "merchantChargeId": "charge-test-3",
        },
    }
    response = client.post(
        "/webhooks/picpay",
        headers={"Authorization": settings.webhook_token, "event-type": "TransactionUpdateMessage"},
        json=payload,
    )
    assert response.status_code == 200
    assert store.find(key)["status"] == "active"


def test_wrong_webhook_amount_does_not_consume_event(tmp_path):
    settings, _public, store, client = _setup(tmp_path)
    key = "LQ-NOPQ-RSTU-VWXY"
    store.provision(key, paid_until=0, provider_subscription_id="subscription-test-4", now="now")
    payload = {
        "id": "event-amount",
        "data": {
            "status": "PAID",
            "amount": settings.price_cents + 1,
            "merchantSubscriptionId": "subscription-test-4",
        },
    }
    denied = client.post(
        "/webhooks/picpay",
        headers={"Authorization": settings.webhook_token},
        json=payload,
    )
    assert denied.status_code == 400
    payload["data"]["amount"] = settings.price_cents
    accepted = client.post(
        "/webhooks/picpay",
        headers={"Authorization": settings.webhook_token},
        json=payload,
    )
    assert accepted.status_code == 200
    assert store.find(key)["status"] == "active"


def test_payment_event_update_is_atomic_when_license_is_missing(tmp_path):
    _settings, _public, store, _client = _setup(tmp_path)
    assert store.apply_payment_event(
        "event-atomic",
        "missing-subscription",
        status="active",
        paid_until=10,
        now="now",
    ) == "not_applied"
    store.provision(
        "LQ-ABCD-EFGH-JKLM",
        paid_until=0,
        provider_subscription_id="missing-subscription",
        now="now",
    )
    assert store.apply_payment_event(
        "event-atomic",
        "missing-subscription",
        status="active",
        paid_until=10,
        now="now",
    ) == "applied"


def test_production_configuration_requires_an_exact_checkout_origin(tmp_path):
    private, _public = chave.gerar_par()
    settings = Settings(
        database=tmp_path / "licencas.db",
        private_key=private,
        webhook_token="webhook",
        environment="production",
        picpay_client_id="client",
        picpay_client_secret="secret",
        picpay_plan_id="plan",
        picpay_merchant_credential="12345678901234",
        picpay_transparent_token="front-token",
        checkout_api_base_url="https://licencas.example.invalid",
    )
    try:
        settings.validate()
    except RuntimeError as exc:
        assert "CHECKOUT_ALLOWED_ORIGINS" in str(exc)
    else:
        raise AssertionError("producao sem origem CORS deveria ser recusada")
