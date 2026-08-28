from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QVBoxLayout, QWidget

from ...config import QUEUES
from ..binding import ConfigBinder


#: Marca da fila que a Riot desligou. Fica na lista de propósito: uma
#: opção que some é lida como defeito do app, e o jogador procura o que
#: não vai achar.
UNAVAILABLE_SUFFIX = "  ·  indisponível agora"


class QueuePage(QWidget):
    """Qual fila jogar e se o app volta para ela sozinho."""

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 28)
        layout.setSpacing(16)

        title = QLabel("FILA")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Defina onde a automação deve procurar a próxima partida.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("contentCard")
        content = QVBoxLayout(card)
        content.setContentsMargins(24, 22, 24, 22)
        content.setSpacing(13)
        label = QLabel("MODO DE PARTIDA")
        label.setObjectName("sectionTitle")
        content.addWidget(label)
        helper = QLabel("A opção fica salva e é usada sempre que a automação iniciar.")
        helper.setObjectName("hint")
        content.addWidget(helper)

        self._combo = QComboBox()
        self._combo.setObjectName("queueSelector")
        for queue_id, name in QUEUES.items():
            self._combo.addItem(name, queue_id)
        index = self._combo.findData(binder.config.queue_id)
        if index >= 0:
            self._combo.setCurrentIndex(index)
        self._combo.currentIndexChanged.connect(self._on_changed)
        content.addWidget(self._combo)

        content.addSpacing(7)
        behavior = QFrame()
        behavior.setObjectName("optionCard")
        behavior_layout = QVBoxLayout(behavior)
        behavior_layout.setContentsMargins(16, 12, 16, 12)
        behavior_layout.setSpacing(7)
        behavior_title = QLabel("COMPORTAMENTO DA FILA")
        behavior_title.setObjectName("cardLabel")
        behavior_layout.addWidget(behavior_title)
        behavior_layout.addWidget(
            binder.checkbox("Entrar na fila e voltar a ela automaticamente", "auto_queue")
        )
        behavior_layout.addWidget(
            binder.checkbox(
                "Só mexer na fila quando eu for o dono da sala",
                "queue_only_as_host",
            )
        )
        content.addWidget(behavior)

        note = QLabel(
            "Em uma sala de amigo, o dono conduz a busca. Com esta proteção "
            "ligada, o app continua cuidando de aceite, banimento e campeão, "
            "mas não cria sala própria nem muda a fila dele."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        content.addWidget(note)
        layout.addWidget(card)
        layout.addStretch(1)

    def set_unavailable(self, queue_ids) -> None:
        """Marca as filas que o cliente recusa agora.

        A escolha do jogador não é trocada por conta própria: descobrir
        dentro de uma Ranqueada que o app te mudou de fila sozinho seria
        muito pior do que ver a fila marcada aqui.
        """
        model = self._combo.model()
        for index in range(self._combo.count()):
            queue_id = self._combo.itemData(index)
            blocked = queue_id in queue_ids
            name = QUEUES.get(queue_id, str(queue_id))
            suffix = UNAVAILABLE_SUFFIX if blocked else ""
            self._combo.setItemText(index, name + suffix)
            model.item(index).setEnabled(not blocked)

    def _on_changed(self, index: int) -> None:
        self._binder.set("queue_id", self._combo.itemData(index))
