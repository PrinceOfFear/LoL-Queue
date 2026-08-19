from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

#: Altura da barra. A janela usa isto para saber onde o arrasto começa.
TITLEBAR_HEIGHT = 46


class TitleBar(QWidget):
    """Barra própria: a janela não tem moldura nativa."""

    def __init__(self, minimize, close, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titlebar")
        self.setFixedHeight(TITLEBAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 12, 0)
        layout.addWidget(QLabel("LOL QUEUE"))
        layout.addStretch(1)
        for text, name, slot in (
            ("—", "windowButton", minimize),
            ("✕", "closeButton", close),
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(slot)
            layout.addWidget(button)
