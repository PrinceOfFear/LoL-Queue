"""Cartao de verificacao de seguranca, sem rede e sem expor dados locais."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...seguranca import SecurityReport, SecurityState


_MARKS = {
    SecurityState.PASSED: "✓",
    SecurityState.INFO: "•",
    SecurityState.WARNING: "!",
    SecurityState.FAILED: "×",
}


class SecurityCard(QFrame):
    """Resume o que foi conferido e deixa uma unica acao clara ao jogador."""

    check_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("securityCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(9)

        heading = QHBoxLayout()
        title = QLabel("SEGURANÇA DO APP")
        title.setObjectName("sectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self._badge = QLabel()
        self._badge.setObjectName("securityBadge")
        heading.addWidget(self._badge)
        layout.addLayout(heading)

        self._status = QLabel()
        self._status.setObjectName("securityStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._checks = QVBoxLayout()
        self._checks.setContentsMargins(0, 2, 0, 2)
        self._checks.setSpacing(6)
        layout.addLayout(self._checks)

        row = QHBoxLayout()
        row.addStretch(1)
        self._action = QPushButton()
        self._action.setObjectName("securityAction")
        self._action.setAccessibleName("Verificar segurança do aplicativo")
        self._action.clicked.connect(self.check_requested)
        row.addWidget(self._action)
        layout.addLayout(row)

        self.show_initial()

    def show_initial(self) -> None:
        self._clear_checks()
        self._set_badge("PRONTO", SecurityState.INFO)
        self._status.setText(
            "Confira a integridade do app, a proteção das atualizações e os limites "
            "da conexão com o cliente do LoL. A verificação é local."
        )
        self._action.setText("Verificar segurança")
        self._action.setEnabled(True)

    def checking(self) -> None:
        self._clear_checks()
        self._set_badge("VERIFICANDO", SecurityState.INFO)
        self._status.setText("Conferindo arquivos e proteções locais. Nenhum dado será enviado.")
        self._action.setText("Verificando...")
        self._action.setEnabled(False)

    def show_report(self, report: SecurityReport) -> None:
        self._clear_checks()
        if report.has_failures:
            badge, state = "ATENÇÃO", SecurityState.FAILED
        elif report.has_warnings:
            badge, state = "PARCIAL", SecurityState.WARNING
        else:
            badge, state = "PROTEGIDO", SecurityState.PASSED
        self._set_badge(badge, state)
        self._status.setText(report.summary)
        for check in report.checks:
            self._checks.addWidget(self._check_row(check.title, check.detail, check.state))
        self._action.setText("Verificar novamente")
        self._action.setEnabled(True)

    def show_error(self) -> None:
        self._clear_checks()
        self._set_badge("INDISPONÍVEL", SecurityState.FAILED)
        self._status.setText(
            "A verificação não terminou. Feche e abra o LoL Queue antes de tentar novamente."
        )
        self._action.setText("Tentar novamente")
        self._action.setEnabled(True)

    def _set_badge(self, text: str, state: SecurityState) -> None:
        self._badge.setText(text)
        self._badge.setProperty("state", state.value)
        self._refresh_style(self._badge)

    def _clear_checks(self) -> None:
        while self._checks.count():
            item = self._checks.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _check_row(self, title: str, detail: str, state: SecurityState) -> QFrame:
        row = QFrame()
        row.setObjectName("securityCheck")
        row.setProperty("state", state.value)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(9)

        mark = QLabel(_MARKS[state])
        mark.setObjectName("securityCheckMark")
        mark.setProperty("state", state.value)
        layout.addWidget(mark)

        words = QVBoxLayout()
        words.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("securityCheckTitle")
        words.addWidget(label)
        note = QLabel(detail)
        note.setObjectName("securityCheckDetail")
        note.setWordWrap(True)
        words.addWidget(note)
        layout.addLayout(words, 1)
        return row

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
