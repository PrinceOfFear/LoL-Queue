"""Eventos em tempo real da API local do League Client.

O cliente publica altera\u00e7\u00f5es de recursos JSON por WebSocket antes de
alguns deles aparecerem (ou desaparecerem) no polling HTTP. Isto \u00e9 especialmente
importante para a notifica\u00e7\u00e3o de PDL, que pode viver s\u00f3 por instantes no
p\u00f3s-jogo.

O protocolo \u00e9 o WAMP 1.0 usado pelo pr\u00f3prio cliente: depois do ``WELCOME``,
``[5, "OnJsonApiEvent"]`` assina o fluxo de altera\u00e7\u00f5es. Como a LCU \u00e9 uma API
local sem contrato p\u00fablico est\u00e1vel, o restante do app ainda conserva o polling
e a leitura do trace como redund\u00e2ncia.
"""

from __future__ import annotations

import base64
import json
import ssl
import threading
from collections.abc import Callable
from typing import Any, Protocol

from .credentials import Credentials

JSON_API_TOPIC = "OnJsonApiEvent"
WAMP_WELCOME = 0
WAMP_EVENT = 8
RECONNECT_DELAY = 2.0
RECEIVE_TIMEOUT = 1.0
OPEN_TIMEOUT = 3.0


class _Socket(Protocol):
    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def send(self, message: str) -> Any: ...

    def close(self) -> Any: ...


def subscription_message() -> str:
    """Monta a assinatura WAMP 1.0 sem depender da biblioteca de socket."""

    return json.dumps([5, JSON_API_TOPIC], separators=(",", ":"))


def decode_json_api_event(message: object) -> dict[str, object] | None:
    """L\u00ea somente um evento WAMP v\u00e1lido de altera\u00e7\u00e3o JSON da LCU.

    O transport pode entregar texto, bytes ou uma lista j\u00e1 decodificada nos
    testes. Nada fora de ``[8, "OnJsonApiEvent", {...}]`` chega ao callback.
    """

    raw = message
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if (
        not isinstance(raw, list)
        or len(raw) < 3
        or raw[0] != WAMP_EVENT
        or raw[1] != JSON_API_TOPIC
        or not isinstance(raw[2], dict)
    ):
        return None
    return raw[2]


def _is_welcome(message: object) -> bool:
    if isinstance(message, (str, bytes, bytearray)):
        try:
            message = json.loads(message)
        except (TypeError, ValueError):
            return False
    return isinstance(message, list) and bool(message) and message[0] == WAMP_WELCOME


def _default_connection(credentials: Credentials) -> _Socket:
    """Abre o WebSocket local com o mesmo Basic Auth do cliente HTTP."""

    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - depende da instala\u00e7\u00e3o final
        raise RuntimeError("biblioteca de WebSocket n\u00e3o est\u00e1 instalada") from exc

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    authorization = base64.b64encode(
        f"riot:{credentials.token}".encode("utf-8")
    ).decode("ascii")
    return connect(
        f"wss://127.0.0.1:{credentials.port}/",
        ssl=context,
        additional_headers={"Authorization": f"Basic {authorization}"},
        subprotocols=["wamp"],
        # Proxy jamais deve interceptar uma conex\u00e3o autenticada de loopback.
        proxy=None,
        open_timeout=OPEN_TIMEOUT,
        ping_interval=None,
    )


class LcuJsonApiEvents:
    """Mant\u00e9m uma assinatura WAMP curta e reinici\u00e1vel em segundo plano.

    A thread n\u00e3o conhece Qt nem grava dados. Ela apenas entrega eventos j\u00e1
    validados ao callback, permitindo que quem captura PDL continue usando o
    mesmo armazenamento thread-safe do polling HTTP.
    """

    def __init__(
        self,
        credentials: Credentials,
        on_event: Callable[[dict[str, object]], None],
        *,
        connection_factory: Callable[[Credentials], _Socket] = _default_connection,
        reconnect_delay: float = RECONNECT_DELAY,
        receive_timeout: float = RECEIVE_TIMEOUT,
    ) -> None:
        self._credentials = credentials
        self._on_event = on_event
        self._connection_factory = connection_factory
        self._reconnect_delay = reconnect_delay
        self._receive_timeout = receive_timeout
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="LoLQueue-LCU-events",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stopped.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stopped.is_set():
            connection: _Socket | None = None
            try:
                connection = self._connection_factory(self._credentials)
                self._listen(connection)
            except Exception:
                # O watcher HTTP ainda trata a queda do cliente. Aqui uma
                # desconex\u00e3o \u00e9 s\u00f3 motivo para reconectar, nunca para derrubar
                # a vigia inteira que controla a fila.
                pass
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
            self._stopped.wait(self._reconnect_delay)

    def _listen(self, connection: _Socket) -> None:
        # A LCU manda o WELCOME primeiro. Assinar antes dele pode funcionar
        # em alguns patches, mas o servidor atual ignora silenciosamente a
        # assinatura antecipada.
        welcome = connection.recv(timeout=self._receive_timeout)
        if not _is_welcome(welcome):
            return
        connection.send(subscription_message())
        while not self._stopped.is_set():
            try:
                message = connection.recv(timeout=self._receive_timeout)
            except TimeoutError:
                continue
            event = decode_json_api_event(message)
            if event is not None:
                self._on_event(event)
