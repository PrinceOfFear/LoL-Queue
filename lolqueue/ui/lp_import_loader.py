"""Valida e grava uma importação manual de PDL fora da thread da tela."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.lp_history import LpImportResult
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class LpImportLoader(QThread):
    """Mantém a interface responsiva enquanto a LCU confere cada linha."""

    ready = Signal(object)

    def __init__(self, history, rows, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self._rows = tuple(rows)

    def run(self) -> None:
        result = LpImportResult(rejected=len(self._rows))
        try:
            credentials = discover()
            if credentials is not None:
                result = self._history.import_manual(LcuClient(credentials), self._rows)
        except Exception:
            # A interface já explica a ação segura: deixar o cliente aberto
            # e atualizar. Não expomos detalhes internos ou da conta aqui.
            result = LpImportResult(rejected=len(self._rows))
        self.ready.emit(result)
