"""Dublês de teste para o cliente da LCU."""

from __future__ import annotations

from lolqueue.lcu.client import ClientClosed, LcuError


class FakeLcuClient:
    """Cliente LCU falso.

    - `responses` mapeia caminho -> payload devolvido pelo GET
    - `failures` são caminhos que levantam LcuError
    - `closed` faz qualquer chamada levantar ClientClosed
    - `calls` grava (método, caminho) na ordem
    """

    def __init__(self, responses=None, failures=None, closed=False):
        self.responses = dict(responses or {})
        self.failures = set(failures or ())
        self.closed = closed
        self.calls: list[tuple[str, str]] = []
        self.payloads: list[tuple[str, object]] = []

    def _record(self, method, path):
        self.calls.append((method, path))
        if self.closed:
            raise ClientClosed("cliente fechado")
        if path in self.failures:
            raise LcuError(f"falha simulada em {path}")

    def get(self, path):
        self._record("GET", path)
        return self.responses.get(path)

    def post(self, path, json=None):
        self._record("POST", path)
        self.payloads.append((path, json))
        return None

    def patch(self, path, json=None):
        self._record("PATCH", path)
        self.payloads.append((path, json))
        return None

    def delete(self, path):
        self._record("DELETE", path)
        return None

    def paths(self, method=None):
        return [p for m, p in self.calls if method is None or m == method]
