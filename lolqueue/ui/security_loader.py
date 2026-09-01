"""Trabalhador da verificacao de seguranca; hashes nunca travam a interface."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..atualizacao import Installation
from ..seguranca import SecurityReport, inspect


class SecurityCheckLoader(QThread):
    """Confere a instalacao em segundo plano, sem rede e sem tocar na GUI."""

    ready = Signal(object, object)

    def __init__(self, installation: Installation, parent=None) -> None:
        super().__init__(parent)
        self._installation = installation

    def run(self) -> None:
        try:
            report: SecurityReport | None = inspect(
                self._installation.root,
                development=self._installation.is_development_checkout,
            )
            error = None
        except Exception as exc:  # a tela mostra so um estado seguro, sem traceback
            report, error = None, exc
        self.ready.emit(report, error)
