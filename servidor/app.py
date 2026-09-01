"""API FastAPI do licenciamento mensal do LoL Queue.

O cliente nunca fala com o PicPay. Ele fala apenas com esta API e recebe um
bilhete Ed25519 curto, amarrado a uma impressao de computador. O pagamento e
confirmado somente pelo webhook autenticado do PicPay; uma requisicao do
cliente jamais consegue marcar a propria assinatura como paga.
"""

from __future__ import annotations

import hmac
import json
import secrets
import re
import time
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lolqueue.licenca import chave as formato

from .config import Settings
from .checkout import render_checkout
from .db import LicenseStore, agora_iso, normalizar_chave, validar_maquina
from .picpay import PicPayClient, PicPayError


MAX_WEBHOOK_BYTES = 256 * 1024
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chave: str = Field(min_length=11, max_length=20)
    maquina: str = Field(min_length=8, max_length=128)
    apelido: str = Field(default="", max_length=80)
    versao: str = Field(default="", max_length=40)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bilhete: str = Field(min_length=20, max_length=4096)
    maquina: str = Field(min_length=8, max_length=128)


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chave: str = Field(min_length=11, max_length=20)
    maquina: str = Field(min_length=8, max_length=128)


class PhoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str = Field(min_length=1, max_length=3, pattern=r"^\d+$")
    area_code: str = Field(min_length=1, max_length=3, pattern=r"^\d+$")
    number: str = Field(min_length=8, max_length=12, pattern=r"^\d+$")
    type: str = Field(default="MOBILE", pattern=r"^(RESIDENTIAL|COMMERCIAL|TEMPORARY|MOBILE)$")


class SubscribeRequest(BaseModel):
    """Dados do cliente e token efemero criado pelo SDK do PicPay."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=254)
    document_type: str = Field(pattern=r"^(CPF|CNPJ|PASSPORT)$")
    document: str = Field(min_length=6, max_length=14, pattern=r"^[A-Za-z0-9]+$")
    phone: PhoneRequest
    card_token: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9._/+-]+$",
    )


def _mes_seguinte(timestamp: int) -> int:
    """Adiciona um mes de calendario, sem o erro de usar sempre 30 dias."""
    atual = datetime.fromtimestamp(timestamp, timezone.utc)
    year, month = atual.year, atual.month + 1
    if month == 13:
        year, month = year + 1, 1
    day = min(atual.day, monthrange(year, month)[1])
    return int(atual.replace(year=year, month=month, day=day).timestamp())


def _provider_status(payload: dict[str, Any]) -> tuple[str, str, int, str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("webhook sem data")
    status = str(data.get("status") or "").strip().upper()
    provider_id = str(
        data.get("merchantSubscriptionId")
        or data.get("subscriptionId")
        or payload.get("merchantSubscriptionId")
        or data.get("merchantChargeId")
        or ""
    ).strip()
    charge_id = str(data.get("merchantChargeId") or "").strip()
    amount = data.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ValueError("webhook sem valor em centavos")
    if not provider_id or len(provider_id) > 128:
        raise ValueError("webhook sem identificador da assinatura")
    return status, provider_id, amount, charge_id


def _nova_chave() -> str:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "LQ-" + "-".join(
        "".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)
    )


def _ticket_for_key(settings: Settings, row, key: str, *, now: int) -> str:
    paid_until = int(row["paid_until"])
    if row["status"] != "active" or paid_until <= now:
        raise PermissionError("assinatura vencida ou cancelada")
    expira = min(
        paid_until + settings.grace_days * 86400,
        now + settings.offline_days * 86400,
    )
    if not settings.private_key:
        raise RuntimeError("LICENSE_PRIVATE_KEY nao configurada")
    licenca = formato.Licenca(
        chave=key,
        maquina=str(row["machine"] or ""),
        expira=expira,
        assinatura_ate=paid_until,
        emitido=now,
        plano=str(row["plan"] or "mensal"),
        apelido="",
        extra={
            "billing": "picpay",
            "currency": settings.currency,
            "price_cents": settings.price_cents,
            "subscription_id": str(row["picpay_subscription_id"] or ""),
        },
    )
    return formato.assinar(licenca, settings.private_key)


class RequestSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("content-length", "")
        try:
            if raw and int(raw) > MAX_WEBHOOK_BYTES:
                return JSONResponse({"erro": "requisicao grande demais"}, status_code=413)
        except ValueError:
            return JSONResponse({"erro": "content-length invalido"}, status_code=400)
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    config.validate()
    store = LicenseStore(config.database)
    docs = None if config.environment == "production" else "/docs"
    app = FastAPI(
        title="LoL Queue License API",
        docs_url=docs,
        redoc_url=None if docs is None else "/redoc",
        openapi_url=None if docs is None else "/openapi.json",
    )
    app.add_middleware(RequestSizeMiddleware)
    if config.environment == "production":
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))
    if config.checkout_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.checkout_allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Accept"],
            allow_credentials=False,
            max_age=600,
        )

    def public_key() -> str:
        if not config.private_key:
            raise HTTPException(status_code=503, detail="licenciamento nao configurado")
        try:
            return formato.publica_de(config.private_key)
        except Exception as exc:  # noqa: BLE001 - segredo nunca vai para a resposta
            raise HTTPException(status_code=503, detail="chave de licenca invalida") from exc

    @app.get("/api/saude")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "servico": "lolqueue-license",
            "plano": "mensal",
            "moeda": config.currency,
            "preco_centavos": config.price_cents,
        }

    @app.get("/checkout", response_class=HTMLResponse)
    def checkout() -> HTMLResponse:
        """Checkout web separado do executavel do jogador."""
        if not config.picpay_merchant_credential or not config.picpay_transparent_token:
            raise HTTPException(status_code=503, detail="checkout PicPay ainda nao configurado")
        html, nonce = render_checkout(
            api_base_url=config.checkout_api_base_url,
            merchant_credential=config.picpay_merchant_credential,
            transparent_token=config.picpay_transparent_token,
            sdk_url=config.picpay_sdk_url,
        )
        api_origin = ""
        if config.checkout_api_base_url:
            parsed_api = urlsplit(config.checkout_api_base_url)
            api_origin = f" https://{parsed_api.netloc}"
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; base-uri 'none'; form-action 'self'; "
                    "frame-ancestors 'none'; style-src 'unsafe-inline'; "
                    f"script-src 'nonce-{nonce}' https://checkout.picpay.com https://checkout-qa.picpay.com; "
                    "connect-src 'self' https://checkout.picpay.com https://checkout-qa.picpay.com "
                    "https://ecommerce-api.svc.picpay.com https://ecommerce-api.svcp.ppay.me"
                    f"{api_origin}"
                ),
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.post("/api/ativar")
    def activate(payload: ActivateRequest) -> dict[str, str]:
        try:
            key = normalizar_chave(payload.chave)
            machine = validar_maquina(payload.maquina)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = store.find(key)
        if row is None:
            raise HTTPException(status_code=404, detail="chave nao encontrada")
        if row["status"] != "active" or int(row["paid_until"]) <= int(time.time()):
            raise HTTPException(status_code=403, detail="assinatura vencida ou cancelada")
        try:
            row = store.bind_and_touch(key, machine, now=agora_iso())
            ticket = _ticket_for_key(config, row, key, now=int(time.time()))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="chave nao encontrada") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"bilhete": ticket}

    @app.post("/api/validar")
    def validate(payload: ValidateRequest) -> dict[str, str]:
        try:
            machine = validar_maquina(payload.maquina)
            checked = formato.conferir(payload.bilhete, public_key(), maquina=machine)
        except (ValueError, formato.LicencaInvalida) as exc:
            raise HTTPException(status_code=400, detail="bilhete invalido") from exc
        row = store.find(checked.chave)
        if row is None or not row["machine"] or row["machine"] != machine:
            raise HTTPException(status_code=403, detail="licenca nao vinculada a este computador")
        try:
            ticket = _ticket_for_key(config, row, checked.chave, now=int(time.time()))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        store.touch(checked.chave, now=agora_iso())
        return {"bilhete": ticket}

    @app.post("/api/liberar")
    def release(payload: ReleaseRequest) -> dict[str, bool]:
        try:
            key = normalizar_chave(payload.chave)
            machine = validar_maquina(payload.maquina)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not store.release(key, machine, now=agora_iso()):
            raise HTTPException(status_code=403, detail="licenca nao pertence a este computador")
        return {"liberado": True}

    @app.post("/api/assinaturas")
    def subscribe(payload: SubscribeRequest) -> dict[str, str]:
        """Inicia a mensalidade sem jamais receber numero ou CVV do cartao."""
        email = payload.email.strip().lower()
        if not _EMAIL_RE.fullmatch(email):
            raise HTTPException(status_code=400, detail="email invalido")
        if not config.picpay_client_id or not config.picpay_client_secret or not config.picpay_plan_id:
            raise HTTPException(status_code=503, detail="PicPay ainda nao foi configurado")
        key = _nova_chave()
        merchant_subscription_id = str(uuid4())
        now = agora_iso()
        store.provision(
            key,
            paid_until=0,
            email=email,
            provider_subscription_id=merchant_subscription_id,
            now=now,
        )
        customer = {
            "name": payload.name.strip(),
            "email": email,
            "documentType": payload.document_type,
            "document": payload.document,
            "phone": {
                "countryCode": payload.phone.country_code,
                "areaCode": payload.phone.area_code,
                "number": payload.phone.number,
                "type": payload.phone.type,
            },
        }
        try:
            provider = PicPayClient(
                config.picpay_api_base,
                config.picpay_client_id,
                config.picpay_client_secret,
                config.picpay_plan_id,
            )
            result = provider.create_subscription(
                customer=customer,
                merchant_subscription_id=merchant_subscription_id,
                temporary_card_token=payload.card_token,
            )
            charges = result.get("charges") if isinstance(result, dict) else None
            charge_id = charges[0] if isinstance(charges, list) and charges and isinstance(charges[0], str) else ""
            store.attach_charge(merchant_subscription_id, charge_id, now=agora_iso())
        except (ValueError, PicPayError) as exc:
            store.update_payment(
                merchant_subscription_id,
                status="canceled",
                paid_until=0,
                now=agora_iso(),
            )
            raise HTTPException(status_code=502, detail="nao foi possivel criar a assinatura") from exc
        return {
            "chave": key,
            "assinatura_id": merchant_subscription_id,
            "status": "aguardando confirmacao do pagamento",
            "plano": "mensal",
            "moeda": config.currency,
            "preco_centavos": str(config.price_cents),
        }

    @app.post("/webhooks/picpay")
    async def picpay_webhook(request: Request) -> dict[str, bool]:
        supplied = request.headers.get("authorization", "")
        if not config.webhook_token or not hmac.compare_digest(supplied, config.webhook_token):
            raise HTTPException(status_code=401, detail="webhook nao autorizado")
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="webhook grande demais")
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            event_id = str(payload.get("id") or "").strip()
            if not event_id or len(event_id) > 128:
                raise ValueError
            status, provider_id, amount, charge_id = _provider_status(payload)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="webhook invalido") from exc
        if amount != config.price_cents:
            raise HTTPException(status_code=400, detail="valor do plano nao confere")
        event_type = request.headers.get("event-type") or request.headers.get("event_type")
        if event_type and event_type != "TransactionUpdateMessage":
            raise HTTPException(status_code=400, detail="tipo de evento PicPay nao suportado")
        row = store.find_by_provider_id(provider_id)
        if row is None:
            # Nao transformar um evento recebido antes do cadastro em uma
            # licenca desconhecida; o suporte pode consultar o event_id.
            raise HTTPException(status_code=404, detail="assinatura nao encontrada")
        now = int(time.time())
        if status in {"PAID", "AUTHORIZED", "CAPTURED", "APPROVED"}:
            paid_until = max(int(row["paid_until"]), now)
            paid_until = _mes_seguinte(paid_until)
            next_status = "active"
        elif status in {"CANCELED", "CANCELLED", "REFUNDED", "CHARGEBACK"}:
            paid_until, next_status = now, "canceled"
        elif status in {"FAILED", "DECLINED", "EXPIRED", "DENIED"}:
            paid_until, next_status = int(row["paid_until"]), "past_due"
        else:
            # Estados desconhecidos nao devem liberar nem revogar acesso.
            return {"ok": True}
        result = store.apply_payment_event(
            event_id,
            provider_id,
            status=next_status,
            paid_until=paid_until,
            charge_id=charge_id,
            now=agora_iso(),
        )
        if result == "duplicate":
            return {"ok": True}  # reentrega do PicPay: idempotente
        if result != "applied":
            raise HTTPException(status_code=409, detail="evento nao aplicado")
        return {"ok": True}

    return app


app = create_app()
