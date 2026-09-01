"""Cliente minimo e seguro para o PicPay Checkout Recorrencia."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import requests


class PicPayError(RuntimeError):
    """Resposta invalida ou falha da API do provedor."""


@dataclass(frozen=True)
class PicPayClient:
    base_url: str
    client_id: str
    client_secret: str
    plan_id: str
    timeout: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("PICPAY_API_BASE precisa ser uma URL HTTPS sem query")
        if not self.client_id or not self.client_secret or not self.plan_id:
            raise ValueError("credenciais e planId do PicPay sao obrigatorios")

    def _url(self, path: str) -> str:
        if not path.startswith("/") or "\\" in path or "?" in path or "#" in path:
            raise ValueError("caminho PicPay invalido")
        parsed = urlsplit(self.base_url.rstrip("/"))
        return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/") + path, "", ""))

    def _post(self, path: str, *, payload: dict, token: str = "") -> dict:
        session = requests.Session()
        session.trust_env = False
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = session.post(
                self._url(path),
                json=payload,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise PicPayError("nao foi possivel falar com o PicPay") from exc
        if 300 <= response.status_code < 400:
            raise PicPayError("o PicPay tentou redirecionar a conexao")
        try:
            body = response.json()
        except ValueError as exc:
            raise PicPayError("resposta invalida do PicPay") from exc
        if response.status_code >= 400 or not isinstance(body, dict):
            raise PicPayError("PicPay recusou a operacao")
        return body

    def access_token(self) -> str:
        body = self._post(
            "/oauth2/token",
            payload={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise PicPayError("PicPay nao devolveu token de acesso")
        return token

    def create_subscription(
        self,
        *,
        customer: dict,
        merchant_subscription_id: str,
        temporary_card_token: str,
    ) -> dict:
        if not temporary_card_token or len(temporary_card_token) > 512:
            raise ValueError("temporaryCardToken invalido")
        payload = {
            "customer": customer,
            "temporaryCardToken": temporary_card_token,
            "planId": self.plan_id,
            "merchantSubscriptionId": merchant_subscription_id,
        }
        return self._post(
            "/recurrency/subscriptions",
            payload=payload,
            token=self.access_token(),
        )

