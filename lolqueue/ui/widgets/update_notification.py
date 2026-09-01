"""Aviso visual de alta prioridade para uma nova release assinada."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...atualizacao import UpdateOffer


class UpdateNotification(QFrame):
    """Banner persistente, visivel em qualquer pagina, para uma atualizacao.

    O cartao de Ajustes continua com o estado detalhado e o progresso. Este
    componente e apenas o lembrete acionavel: ele aparece quando o manifesto
    assinado confirma uma versao nova e some quando o usuario o dispensa.
    """

    update_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("updateNotification")
        self.setAccessibleName("Notificacao de nova atualizacao")
        self._offer: UpdateOffer | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 12, 12)
        layout.setSpacing(12)

        icon = QLabel("↑")
        icon.setObjectName("updateNotificationIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        eyebrow = QLabel("NOVA ATUALIZAÇÃO DISPONÍVEL")
        eyebrow.setObjectName("updateNotificationEyebrow")
        copy.addWidget(eyebrow)
        self._title = QLabel()
        self._title.setObjectName("updateNotificationTitle")
        self._title.setWordWrap(True)
        copy.addWidget(self._title)
        self._detail = QLabel()
        self._detail.setObjectName("updateNotificationDetail")
        self._detail.setWordWrap(True)
        copy.addWidget(self._detail)
        layout.addLayout(copy, 1)

        self._action = QPushButton("ATUALIZAR AGORA")
        self._action.setObjectName("updateNotificationAction")
        self._action.setAccessibleName("Atualizar agora")
        self._action.clicked.connect(self.update_requested.emit)
        layout.addWidget(self._action)

        dismiss = QPushButton("×")
        dismiss.setObjectName("updateNotificationDismiss")
        dismiss.setAccessibleName("Dispensar aviso de atualização")
        dismiss.setToolTip("Dispensar este aviso")
        dismiss.clicked.connect(self.hide_notification)
        layout.addWidget(dismiss)

        self.hide()

    @property
    def offer(self) -> UpdateOffer | None:
        return self._offer

    def show_offer(self, offer: UpdateOffer) -> None:
        self._offer = offer
        self._title.setText(f"LoL Queue {offer.version} já está pronta para instalar")
        self._detail.setText(
            "Baixe a release assinada para receber correções e melhorias. "
            "O app só reinicia depois de conferir a integridade do pacote."
        )
        self._action.setText("ATUALIZAR AGORA")
        self._action.setEnabled(True)
        self.show()
        self.raise_()

    def checking(self) -> None:
        self._title.setText("Procurando uma release oficial...")
        self._detail.setText("A assinatura e a integridade serão conferidas antes de qualquer download.")
        self._action.setText("VERIFICANDO...")
        self._action.setEnabled(False)
        # A consulta nao e um alerta: o banner so entra na tela quando a
        # release assinada foi confirmada, evitando um falso "ha update".
        self.hide()

    def downloading(self, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        self._title.setText(f"Atualizando o LoL Queue · {percent}%")
        self._detail.setText("O pacote está sendo baixado e conferido. A instalação atual continua preservada.")
        self._action.setText("BAIXANDO...")
        self._action.setEnabled(False)
        self.show()

    def preparing_restart(self) -> None:
        self._title.setText("Atualização conferida. Reiniciando...")
        self._detail.setText("A versão anterior fica guardada até a nova abrir corretamente.")
        self._action.setText("REINICIANDO...")
        self._action.setEnabled(False)
        self.show()

    def hide_notification(self) -> None:
        self.hide()
