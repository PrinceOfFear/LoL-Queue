from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QThread, Signal

from ..core.icons import IconStore
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class IconLoader(QThread):
    """Baixa os retratos dos campeões numa thread própria.

    Não pode rodar na thread do watcher: parar o polling por vários
    segundos para baixar ~170 imagens custaria o aceite automático da
    partida. Usa uma conexão própria com o cliente do LoL pelo mesmo
    motivo — nada é compartilhado entre as duas threads.
    """

    done = Signal()

    def __init__(
        self,
        champion_ids: Iterable[int],
        store: IconStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ids = list(champion_ids)
        self._store = store
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        credentials = discover()
        if credentials is None:
            return
        client = LcuClient(credentials, timeout=5.0)
        self._store.fetch_missing(client, self._ids, lambda: self._running)
        if self._running:
            self.done.emit()
