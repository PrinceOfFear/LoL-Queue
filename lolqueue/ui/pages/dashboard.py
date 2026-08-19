from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..widgets.log_pane import LogPane
from ..widgets.status_ring import StatusRing


class DashboardPage(QWidget):
    """Anel de estado, o botão que liga o motor e o registro."""

    #: O usuário pediu para inverter o motor. Quem decide o que isso
    #: significa é a janela, que é quem fala com o watcher.
    toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 10, 40, 28)
        layout.setSpacing(18)
        layout.addStretch(1)

        self.ring = StatusRing()
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)

        self._button = QPushButton("INICIAR")
        self._button.setObjectName("primaryButton")
        self._button.setProperty("running", "false")
        self._button.clicked.connect(self.toggled)
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)

        hint = QLabel("F5 iniciar        F6 parar")
        hint.setObjectName("hint")
        layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)
        self._log = LogPane()
        layout.addWidget(self._log)

    def set_running(self, running: bool) -> None:
        self._button.setProperty("running", "true" if running else "false")
        self._button.setText("PARAR" if running else "INICIAR")
        # Propriedade dinâmica só muda a cor depois de repintar.
        self._button.style().unpolish(self._button)
        self._button.style().polish(self._button)

    def set_log_folder(self, folder) -> None:
        self._log.set_folder(folder)

    def append(self, message: str) -> None:
        self._log.append(message)
