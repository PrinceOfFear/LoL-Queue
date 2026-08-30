"""Dublês de teste para o cliente da LCU."""

from __future__ import annotations

from lolqueue.lcu import endpoints
from lolqueue.lcu.client import ClientClosed, LcuError


class FakeLcuClient:
    """Cliente LCU falso.

    - `responses` mapeia caminho -> payload devolvido pelo GET
    - `posts` mapeia caminho -> payload devolvido pelo POST, para quando
      a resposta importa (criar página de runas devolve o id da nova)
    - `failures` são caminhos que levantam LcuError; para derrubar só um
      verbo do mesmo caminho — o POST de `/lol-perks/v1/pages` sem levar
      junto o GET — vale a tupla `("POST", caminho)`
    - `deaf` são caminhos que respondem 2xx e não fazem nada: é a
      mentira que o cliente de verdade conta, e sem ela não dá para
      testar quem confere depois de escrever
    - `closed` faz qualquer chamada levantar ClientClosed
    - `calls` grava (método, caminho) na ordem

    As páginas de runas são o único estado que este dublê simula, e
    simula porque o código que as escreve agora relê o que escreveu: um
    POST em `/lol-perks/v1/pages` guarda a página, um PUT em
    `/lol-perks/v1/currentpage` a torna a ativa, e o GET de
    `currentpage` devolve essa. Sem isso todo teste de runa provaria
    apenas que a chamada saiu.
    """

    def __init__(
        self,
        responses=None,
        failures=None,
        closed=False,
        posts=None,
        deaf=None,
    ):
        self.responses = dict(responses or {})
        self.posts = dict(posts or {})
        self.failures = set(failures or ())
        self.deaf = set(deaf or ())
        self.closed = closed
        self.calls: list[tuple[str, str]] = []
        self.payloads: list[tuple[str, object]] = []
        # id -> corpo da página, como o cliente a devolveria depois.
        self.pages: dict[object, dict] = {}

    def _record(self, method, path):
        self.calls.append((method, path))
        if self.closed:
            raise ClientClosed("cliente fechado")
        if path in self.failures or (method, path) in self.failures:
            raise LcuError(f"falha simulada em {path}")

    def _heeds(self, method, path) -> bool:
        return path not in self.deaf and (method, path) not in self.deaf

    def get(self, path):
        self._record("GET", path)
        return self.responses.get(path)

    def post(self, path, json=None):
        self._record("POST", path)
        self.payloads.append((path, json))
        answer = self.posts.get(path)
        if path == endpoints.PERK_PAGES and self._heeds("POST", path):
            page = dict(json or {})
            page.update(answer if isinstance(answer, dict) else {})
            page.setdefault("isDeletable", True)
            if page.get("id") is not None:
                self.pages[page["id"]] = page
        return answer

    def put(self, path, json=None):
        self._record("PUT", path)
        self.payloads.append((path, json))
        if path == endpoints.PERK_CURRENT_PAGE and self._heeds("PUT", path):
            self.responses[path] = self.pages.get(json, {"id": json})
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
