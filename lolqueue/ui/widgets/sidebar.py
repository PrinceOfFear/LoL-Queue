from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SECTIONS = ("Painel", "Campeões", "Fila", "Ajustes")


class Sidebar(QWidget):
    """Navegação lateral com indicador de conexão no rodapé."""

    navigated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 22, 0, 0)
        layout.setSpacing(2)

        brand = QLabel("LOL QUEUE")
        brand.setObjectName("sectionTitle")
        brand.setContentsMargins(21, 0, 0, 22)
        layout.addWidget(brand)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, title in enumerate(SECTIONS):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self._group.addButton(button, index)
            layout.addWidget(button)
        self._group.idClicked.connect(self.navigated.emit)

        layout.addStretch(1)
        self._connection = QLabel()
        self._connection.setObjectName("connectionDot")
        layout.addWidget(self._connection)
        self.set_connected(False)

    def set_connected(self, connected: bool) -> None:
        label = "Conectado" if connected else "Desconectado"
        color = "#0AC8B9" if connected else "#A09B8C"
        self._connection.setText(f'<span style="color:{color}">&#9679;</span> {label}')
