from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_LINES = 400


class LogPane(QWidget):
    """Log recolhível. Começa fechado: não é o protagonista da tela."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._folder = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)

        self._toggle = QPushButton("▸  REGISTRO")
        self._toggle.setObjectName("logToggle")
        self._toggle.setCheckable(True)
        self._toggle.toggled.connect(self._on_toggled)
        head.addWidget(self._toggle)
        head.addStretch(1)

        # Sem este botão o arquivo do registro existiria sem que ninguém
        # soubesse onde — ele fica enterrado no AppData.
        self._open = QPushButton("abrir pasta")
        self._open.setObjectName("logToggle")
        self._open.clicked.connect(self._open_folder)
        self._open.hide()
        head.addWidget(self._open)

        layout.addLayout(head)

        self._text = QPlainTextEdit()
        self._text.setObjectName("logPane")
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_LINES)
        self._text.setFixedHeight(120)
        self._text.hide()
        layout.addWidget(self._text)

    def set_folder(self, folder) -> None:
        """Diz onde mora o registro em arquivo, revelando o botão."""
        self._folder = folder
        self._open.setVisible(folder is not None)

    def _open_folder(self) -> None:
        if self._folder is None:
            return
        # Pode ainda não existir: o registro só cria o diretório na
        # primeira linha gravada, e o botão aparece antes disso.
        self._folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folder)))

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setText("▾  REGISTRO" if checked else "▸  REGISTRO")
        self._text.setVisible(checked)

    def append(self, message: str) -> None:
        self._text.appendPlainText(f"{time.strftime('%H:%M:%S')}  {message}")
