from __future__ import annotations

import time

from PySide6.QtWidgets import (
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._toggle = QPushButton("▸  REGISTRO")
        self._toggle.setObjectName("logToggle")
        self._toggle.setCheckable(True)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._text = QPlainTextEdit()
        self._text.setObjectName("logPane")
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_LINES)
        self._text.setFixedHeight(120)
        self._text.hide()
        layout.addWidget(self._text)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setText("▾  REGISTRO" if checked else "▸  REGISTRO")
        self._text.setVisible(checked)

    def append(self, message: str) -> None:
        self._text.appendPlainText(f"{time.strftime('%H:%M:%S')}  {message}")
