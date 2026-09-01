"""Cartao de atualizacao remota, sem fazer rede na thread da interface."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...atualizacao import UpdateOffer, current_version, updates_configured


def _size(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(max(0, value))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


class UpdateCard(QFrame):
    """Mostra o estado do update e delega trabalho pesado para a janela."""

    check_requested = Signal()
    download_requested = Signal()

    def __init__(
        self,
        *,
        configured: bool | None = None,
        version: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("updateCard")
        self._configured = updates_configured() if configured is None else configured
        self._version = version or current_version()
        self._offer: UpdateOffer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel("ATUALIZACOES DO APP")
        title.setObjectName("sectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self._version_badge = QLabel(f"VERSAO {self._version}")
        self._version_badge.setObjectName("updateVersion")
        heading.addWidget(self._version_badge)
        layout.addLayout(heading)

        self._status = QLabel()
        self._status.setObjectName("updateStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._detail = QLabel()
        self._detail.setObjectName("hint")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        row = QHBoxLayout()
        row.addStretch(1)
        self._action = QPushButton()
        self._action.setObjectName("updateAction")
        self._action.clicked.connect(self._on_action)
        row.addWidget(self._action)
        layout.addLayout(row)
        self._show_initial()

    @property
    def offer(self) -> UpdateOffer | None:
        return self._offer

    def _show_initial(self) -> None:
        if not self._configured:
            self._status.setText("Atualizacao remota ainda nao configurada nesta distribuicao.")
            self._detail.setText(
                "Quando a versao oficial for ligada a um repositorio GitHub assinado, "
                "o botao aparecera aqui. Nenhum arquivo sera baixado ate isso existir."
            )
            self._action.setText("Atualizacao indisponivel")
            self._action.setEnabled(False)
            return
        self._status.setText("Verifique se existe uma nova versao oficial.")
        self._detail.setText("A verificacao confere assinatura e integridade antes de oferecer qualquer download.")
        self._action.setText("Verificar atualizacoes")
        self._action.setEnabled(True)

    def _on_action(self) -> None:
        if self._offer is None:
            self.check_requested.emit()
        else:
            self.download_requested.emit()

    def checking(self) -> None:
        self._offer = None
        self._status.setText("Verificando a release oficial...")
        self._detail.setText("A interface continua aberta enquanto a assinatura do manifesto e conferida.")
        self._action.setText("Verificando...")
        self._action.setEnabled(False)

    def show_current(self) -> None:
        self._offer = None
        self._status.setText("Seu LoL Queue ja esta atualizado.")
        self._detail.setText("Nenhum download foi feito.")
        self._action.setText("Verificar novamente")
        self._action.setEnabled(True)

    def show_offer(self, offer: UpdateOffer) -> None:
        self._offer = offer
        self._status.setText(f"Versao {offer.version} disponivel para esta instalacao.")
        notes = offer.notes.strip() or "A release oficial nao trouxe notas adicionais."
        self._detail.setText(
            f"Pacote compativel: {_size(offer.artifact.size)}. {notes}"
        )
        self._action.setText("Baixar e reiniciar")
        self._action.setEnabled(True)

    def downloading(self, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        self._status.setText(f"Baixando e conferindo a atualizacao: {percent}%")
        self._detail.setText(f"{_size(done)} de {_size(total)}. A instalacao atual ainda nao foi alterada.")
        self._action.setText("Baixando...")
        self._action.setEnabled(False)

    def preparing_restart(self) -> None:
        self._status.setText("Atualizacao conferida. Reiniciando para aplicar com seguranca...")
        self._detail.setText("A versao anterior fica guardada ate a nova estar pronta para abrir.")
        self._action.setText("Reiniciando...")
        self._action.setEnabled(False)

    def show_error(self, message: str) -> None:
        self._offer = None
        self._status.setText("Nao foi possivel atualizar agora.")
        self._detail.setText(message)
        self._action.setText("Tentar novamente")
        self._action.setEnabled(self._configured)

    def show_unavailable(self, detail: str) -> None:
        """Desliga o botao quando esta copia nao pode ser sobrescrita.

        Um clone de desenvolvimento pode conter alteracoes que ainda nao
        foram entregues. A verificacao remota continua tecnicamente possivel,
        mas oferecer "baixar e reiniciar" ali seria enganoso, pois a camada
        de aplicacao corretamente recusaria apagar o clone depois.
        """

        self._offer = None
        self._status.setText("Atualizacao automatica indisponivel nesta copia.")
        self._detail.setText(detail)
        self._action.setText("Atualizacao indisponivel")
        self._action.setEnabled(False)
