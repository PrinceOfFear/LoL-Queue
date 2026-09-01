"""Configuracao segura do servidor de licencas.

Nenhum segredo tem valor padrao. Em producao, a aplicacao deve ser iniciada
com ``LICENSE_PRIVATE_KEY`` e ``PICPAY_WEBHOOK_TOKEN`` fornecidos pelo
gerenciador de segredos do host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} precisa ser um numero inteiro") from exc
    if value < minimum:
        raise RuntimeError(f"{name} precisa ser maior ou igual a {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    """Valores de execucao, sem imprimir material sensivel."""

    database: Path
    private_key: str
    webhook_token: str
    environment: str = "development"
    picpay_client_id: str = ""
    picpay_client_secret: str = ""
    picpay_plan_id: str = ""
    picpay_api_base: str = "https://ecommerce-api.svc.picpay.com"
    picpay_merchant_credential: str = ""
    picpay_transparent_token: str = ""
    picpay_sdk_url: str = "https://checkout.picpay.com/cdn/pp-transparent-v1.0.0.js"
    checkout_api_base_url: str = ""
    checkout_allowed_origins: tuple[str, ...] = ()
    price_cents: int = 2000
    currency: str = "BRL"
    grace_days: int = 3
    offline_days: int = 7
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    @classmethod
    def from_env(cls) -> "Settings":
        base = Path(os.environ.get("LICENSE_DATABASE", "servidor/licencas.db"))
        hosts = tuple(
            item.strip()
            for item in os.environ.get("LICENSE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
            if item.strip()
        ) or ("localhost",)
        settings = cls(
            database=base.expanduser().resolve(),
            private_key=os.environ.get("LICENSE_PRIVATE_KEY", "").strip(),
            webhook_token=os.environ.get("PICPAY_WEBHOOK_TOKEN", "").strip(),
            environment=os.environ.get("LICENSE_ENV", "development").strip().lower(),
            picpay_client_id=os.environ.get("PICPAY_CLIENT_ID", "").strip(),
            picpay_client_secret=os.environ.get("PICPAY_CLIENT_SECRET", "").strip(),
            picpay_plan_id=os.environ.get("PICPAY_PLAN_ID", "").strip(),
            picpay_api_base=os.environ.get(
                "PICPAY_API_BASE", "https://ecommerce-api.svc.picpay.com"
            ).strip().rstrip("/"),
            picpay_merchant_credential=os.environ.get(
                "PICPAY_MERCHANT_CREDENTIAL", ""
            ).strip(),
            picpay_transparent_token=os.environ.get(
                "PICPAY_TRANSPARENT_TOKEN", ""
            ).strip(),
            picpay_sdk_url=os.environ.get(
                "PICPAY_SDK_URL",
                "https://checkout.picpay.com/cdn/pp-transparent-v1.0.0.js",
            ).strip(),
            checkout_api_base_url=os.environ.get("CHECKOUT_API_BASE_URL", "")
            .strip()
            .rstrip("/"),
            checkout_allowed_origins=tuple(
                item.strip()
                for item in os.environ.get("CHECKOUT_ALLOWED_ORIGINS", "").split(",")
                if item.strip()
            ),
            price_cents=_int_env("LICENSE_PRICE_CENTS", 2000),
            currency=os.environ.get("LICENSE_CURRENCY", "BRL").strip().upper(),
            grace_days=_int_env("LICENSE_GRACE_DAYS", 3, minimum=0),
            offline_days=_int_env("LICENSE_OFFLINE_DAYS", 7),
            allowed_hosts=hosts,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.currency != "BRL":
            raise RuntimeError(
                "PicPay Checkout deste servidor usa BRL; confirme o preco antes de cobrar"
            )
        if self.environment == "production":
            if not self.private_key:
                raise RuntimeError("LICENSE_PRIVATE_KEY nao configurada em producao")
            if not self.webhook_token:
                raise RuntimeError("PICPAY_WEBHOOK_TOKEN nao configurado em producao")
            if not self.picpay_merchant_credential or not self.picpay_transparent_token:
                raise RuntimeError(
                    "PICPAY_MERCHANT_CREDENTIAL e PICPAY_TRANSPARENT_TOKEN "
                    "sao obrigatorios para o checkout em producao"
                )
            if not self.checkout_api_base_url:
                raise RuntimeError("CHECKOUT_API_BASE_URL nao configurada em producao")
        picpay = urlsplit(self.picpay_api_base)
        if (
            picpay.scheme != "https"
            or not picpay.netloc
            or picpay.username
            or picpay.password
            or picpay.query
            or picpay.fragment
        ):
            raise RuntimeError("PICPAY_API_BASE precisa usar HTTPS")
        if self.environment == "production" and "*" in self.allowed_hosts:
            raise RuntimeError("LICENSE_ALLOWED_HOSTS nao pode usar wildcard em producao")
        if self.picpay_merchant_credential and not self.picpay_merchant_credential.isdigit():
            raise RuntimeError("PICPAY_MERCHANT_CREDENTIAL precisa conter apenas digitos")
        for name, value in (
            ("PICPAY_TRANSPARENT_TOKEN", self.picpay_transparent_token),
            ("PICPAY_SDK_URL", self.picpay_sdk_url),
        ):
            if value and any(char.isspace() for char in value):
                raise RuntimeError(f"{name} nao pode conter espacos")
        if self.picpay_sdk_url:
            sdk = urlsplit(self.picpay_sdk_url)
            allowed_sdk_hosts = {"checkout.picpay.com"}
            if self.environment != "production":
                allowed_sdk_hosts.add("checkout-qa.picpay.com")
            if (
                sdk.scheme != "https"
                or sdk.netloc not in allowed_sdk_hosts
                or sdk.query
                or sdk.fragment
            ):
                raise RuntimeError("PICPAY_SDK_URL precisa ser um CDN HTTPS oficial do PicPay")
        if self.checkout_api_base_url:
            checkout = urlsplit(self.checkout_api_base_url)
            if (
                checkout.scheme != "https"
                or not checkout.netloc
                or checkout.username
                or checkout.password
                or checkout.query
                or checkout.fragment
            ):
                raise RuntimeError("CHECKOUT_API_BASE_URL precisa ser HTTPS sem credenciais ou query")
        for origin in self.checkout_allowed_origins:
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme != "https"
                or not parsed_origin.netloc
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise RuntimeError(
                    "CHECKOUT_ALLOWED_ORIGINS deve conter apenas origens HTTPS exatas"
                )
        if self.environment == "production" and not self.checkout_allowed_origins:
            raise RuntimeError(
                "CHECKOUT_ALLOWED_ORIGINS precisa listar a origem HTTPS do checkout"
            )
