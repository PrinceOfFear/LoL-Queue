from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

from ...config import QUEUES
from ..binding import ConfigBinder


class QueuePage(QWidget):
    """Qual fila jogar e se o app volta para ela sozinho."""

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 28)
        layout.setSpacing(14)

        title = QLabel("FILA")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._combo = QComboBox()
        for queue_id, name in QUEUES.items():
            self._combo.addItem(name, queue_id)
        index = self._combo.findData(binder.config.queue_id)
        if index >= 0:
            self._combo.setCurrentIndex(index)
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)

        layout.addWidget(
            binder.checkbox("Entrar na fila e voltar a ela automaticamente", "auto_queue")
        )
        layout.addWidget(
            binder.checkbox(
                "Só mexer na fila quando eu for o dono da sala",
                "queue_only_as_host",
            )
        )

        note = QLabel(
            "Na sala de um amigo, quem conduz a fila é o dono dela. Com isto "
            "ligado o app não inicia a busca nem abre uma sala própria quando "
            "a partida acaba — continua aceitando, banindo e escolhendo "
            "campeão normalmente."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch(1)

    def _on_changed(self, index: int) -> None:
        self._binder.set("queue_id", self._combo.itemData(index))
