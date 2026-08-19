from __future__ import annotations

from typing import Any

import requests
import urllib3

from .credentials import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LcuError(RuntimeError):
    """Falha ao falar com o cliente do LoL."""


class ClientClosed(LcuError):
    """O cliente do LoL não está mais aceitando conexões."""


class LcuClient:
    """Sessão HTTP autenticada contra o cliente local do LoL.

    A verificação TLS fica desligada porque o certificado da Riot é
    autoassinado. É aceitável apenas porque o destino é sempre loopback.
    """

    def __init__(
        self,
        credentials: Credentials,
        timeout: float = 2.0,
        session: Any | None = None,
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._session.auth = ("riot", credentials.token)
        self._session.verify = False

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, json: Any | None = None) -> Any:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: Any | None = None) -> Any:
        return self._request("PUT", path, json=json)

    def patch(self, path: str, json: Any | None = None) -> Any:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def raw(self, path: str) -> bytes:
        """Corpo sem interpretar. Para imagens, que não são JSON."""
        return self._send("GET", path).content

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._send(method, path, **kwargs)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise LcuError(f"{method} {path} devolveu JSON inválido") from exc

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._credentials.base_url}{path}"
        try:
            response = self._session.request(
                method, url, timeout=self._timeout, **kwargs
            )
        except requests.exceptions.ConnectionError as exc:
            raise ClientClosed("cliente do LoL fechado") from exc
        except requests.exceptions.RequestException as exc:
            raise LcuError(f"{method} {path} falhou: {exc}") from exc

        if response.status_code >= 400:
            raise LcuError(f"{method} {path} respondeu {response.status_code}")
        return response
