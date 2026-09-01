"""Tela curta de ativacao para builds comerciais."""

from __future__ import annotations

import webbrowser

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...licenca import cliente, porta


class LicenseDialog(QDialog):
    """Pede a chave e nao deixa a janela principal abrir sem bilhete valido."""

    def __init__(self, version: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ativar o LoL Queue")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(
            """
            QDialog { background: #0A1428; color: #F0E6D2; }
            QLabel { color: #F0E6D2; }
            QLabel#detail { color: #A09B8C; }
            QLineEdit { background: #061223; border: 1px solid #1E3A5F;
                        border-radius: 6px; padding: 9px; color: #F0E6D2; }
            QPushButton { background: #0AC8B9; border: 0; border-radius: 6px;
                          padding: 8px 16px; color: #061223; font-weight: 600; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        title = QLabel("Sua assinatura libera este computador")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        detail = QLabel(
            "Digite a chave recebida após o pagamento mensal. A licença fica "
            "presa a este PC e é renovada pelo servidor."
        )
        detail.setObjectName("detail")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self._key = QLineEdit()
        self._key.setPlaceholderText("LQ-XXXX-XXXX-XXXX")
        self._key.setMaxLength(20)
        self._key.setClearButtonEnabled(True)
        layout.addWidget(self._key)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._activate_button = buttons.addButton(
            "Ativar", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._buy_button = buttons.addButton(
            "Assinar R$ 20/mês", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.rejected.connect(self.reject)
        self._activate_button.clicked.connect(lambda: self._activate(version))
        self._buy_button.clicked.connect(self._open_checkout)
        layout.addWidget(buttons)
        self._key.returnPressed.connect(lambda: self._activate(version))

    def _open_checkout(self) -> None:
        try:
            webbrowser.open(porta.checkout_url(), new=2)
            self._status.setStyleSheet("color: #A09B8C;")
            self._status.setText("A página segura de pagamento foi aberta no navegador.")
        except cliente.ErroDeRede as exc:
            self._status.setStyleSheet("color: #E84057;")
            self._status.setText(str(exc))

    def _activate(self, version: str) -> None:
        self._activate_button.setEnabled(False)
        self._status.setStyleSheet("color: #A09B8C;")
        self._status.setText("Conferindo a assinatura…")
        result = porta.ativar(self._key.text(), versao=version)
        self._activate_button.setEnabled(True)
        if result.liberado:
            self._status.setStyleSheet("color: #0AC8B9;")
            self._status.setText(result.motivo)
            self.accept()
            return
        self._status.setStyleSheet("color: #E84057;")
        self._status.setText(result.motivo)
