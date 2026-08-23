from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...resources import asset_path


#: A ordem manda: o índice de cada seção é o da página correspondente na
#: pilha da janela, e os dois são montados em lugares diferentes. Mexer
#: aqui sem mexer lá troca as páginas de botão — é o que o teste de
#: alinhamento em `test_window` existe para pegar.
SECTIONS = (
    ("Painel", "nav-dashboard.svg"),
    ("Análise", "nav-analysis.svg"),
    ("Histórico", "nav-history.svg"),
    ("Campeões", "nav-champions.svg"),
    ("Fila", "nav-queue.svg"),
    ("Ajustes", "nav-settings.svg"),
)


class Sidebar(QWidget):
    """Navegação lateral com indicador de conexão no rodapé."""

    navigated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(224)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 14)
        layout.setSpacing(5)

        brand = QWidget()
        brand.setObjectName("brandBlock")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(12, 10, 10, 10)
        brand_layout.setSpacing(10)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setPixmap(QIcon(str(asset_path("logo-mark.svg"))).pixmap(32, 32))
        brand_layout.addWidget(mark)
        words = QVBoxLayout()
        words.setSpacing(0)
        title = QLabel("LOL QUEUE")
        title.setObjectName("brandTitle")
        words.addWidget(title)
        subtitle = QLabel("CENTRAL DE FILA")
        subtitle.setObjectName("brandSubtitle")
        words.addWidget(subtitle)
        brand_layout.addLayout(words, 1)
        layout.addWidget(brand)
        layout.addSpacing(12)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (title, icon) in enumerate(SECTIONS):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setIcon(QIcon(str(asset_path(icon))))
            button.setIconSize(QSize(19, 19))
            button.setToolTip(title)
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
        state = "online" if connected else "offline"
        self._connection.setProperty("state", state)
        self._connection.setText(f"●  CLIENTE {label.upper()}")
        self._connection.style().unpolish(self._connection)
        self._connection.style().polish(self._connection)
