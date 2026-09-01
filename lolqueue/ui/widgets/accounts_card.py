"""A central visual dos perfis do LoL Queue neste computador.

O cartão recebe dados já prontos; ele não lê disco nem conversa com o
cliente. Assim a tela pode explicar, de relance, qual perfil está em uso,
qual é o modelo e qual ação é segura naquele momento, sem duplicar a regra de
negócio que mora na janela e em :mod:`lolqueue.core.accounts`.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# O tema geral dá a identidade ao app. Estas regras ficam deliberadamente
# locais para que a central de contas tenha uma hierarquia própria sem mudar
# nenhuma outra página.
_ACCOUNT_STYLES = """
QFrame#accountsCard {
    background: rgba(9, 27, 49, 230);
    border: 1px solid rgba(126, 167, 201, 104);
    border-radius: 15px;
}
QFrame#accountsOverview {
    background: rgba(7, 22, 41, 174);
    border: 1px solid rgba(92, 145, 183, 86);
    border-radius: 11px;
}
QFrame#accountEntry {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(25, 58, 88, 192), stop:1 rgba(10, 30, 54, 224));
    border: 1px solid rgba(116, 161, 195, 88);
    border-left: 3px solid rgba(111, 163, 200, 148);
    border-radius: 11px;
}
QFrame#accountEntry[state="active"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(13, 83, 94, 196), stop:1 rgba(9, 38, 61, 230));
    border-color: rgba(55, 210, 196, 156);
    border-left-color: #0AC8B9;
}
QFrame#accountEntry[state="main"] { border-left-color: #C8AA6E; }
QFrame#accountEntry[state="active-main"] {
    border-left-color: #6FE6DA;
    border-color: rgba(200, 170, 110, 154);
}
QFrame#accountEntry:hover { border-color: rgba(200, 170, 110, 172); }
QLabel#accountsHeading {
    color: #F3DEAA;
    font-family: "Beaufort for LOL";
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#accountsSummary { color: #B7CBDB; font-size: 11px; line-height: 1.35; }
QLabel#accountsListLabel {
    color: #9FBBCE;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.5px;
}
QLabel#accountName { color: #F2F7FA; font-size: 14px; font-weight: 800; }
QLabel#accountMeta { color: #9EB7CA; font-size: 10px; font-weight: 600; }
QLabel#accountPill {
    border-radius: 7px;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 4px 7px;
}
QLabel#accountPill[tone="gold"] {
    background: rgba(200, 170, 110, 28);
    border: 1px solid rgba(226, 197, 130, 134);
    color: #F3DDA2;
}
QLabel#accountPill[tone="teal"] {
    background: rgba(10, 200, 185, 25);
    border: 1px solid rgba(76, 220, 208, 136);
    color: #98F3E9;
}
QLabel#accountPill[tone="blue"] {
    background: rgba(91, 151, 198, 28);
    border: 1px solid rgba(128, 182, 222, 110);
    color: #B8DCF6;
}
QLabel#accountPill[tone="muted"] {
    background: rgba(95, 124, 148, 25);
    border: 1px solid rgba(135, 163, 185, 92);
    color: #B5C7D5;
}
QPushButton#accountAction {
    background: rgba(31, 63, 92, 154);
    border: 1px solid rgba(125, 171, 204, 108);
    border-radius: 7px;
    color: #E3EDF3;
    font-size: 10px;
    font-weight: 700;
    padding: 6px 9px;
}
QPushButton#accountAction:hover {
    background: rgba(18, 113, 122, 158);
    border-color: rgba(97, 226, 214, 170);
    color: #F5FFFD;
}
QPushButton#accountAction[kind="primary"] {
    background: rgba(13, 113, 118, 144);
    border-color: rgba(64, 216, 202, 160);
    color: #B8FFF5;
}
QPushButton#accountAction[kind="danger"] {
    background: rgba(101, 39, 54, 88);
    border-color: rgba(210, 101, 117, 112);
    color: #F2BBC3;
}
QPushButton#accountAction[kind="danger"]:hover {
    background: rgba(151, 48, 67, 136);
    border-color: rgba(244, 124, 139, 174);
    color: #FFE4E8;
}
QPushButton#accountAction:disabled {
    background: rgba(24, 42, 60, 104);
    border-color: rgba(83, 112, 137, 76);
    color: #638096;
}
"""


class AccountsCard(QFrame):
    """Perfis lembrados, o modelo principal e ações seguras por estado."""

    #: A conta que o usuário quer promover a principal.
    main_requested = Signal(str)
    #: A conta que o usuário quer tirar do histórico.
    forget_requested = Signal(str)
    #: A conta cujas configurações de dentro do jogo devem virar modelo.
    capture_requested = Signal(str)
    #: A conta que deve largar o modelo que guardou.
    clear_requested = Signal(str)
    #: A conta que quer receber o modelo agora, sem esperar.
    apply_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("accountsCard")
        self.setStyleSheet(_ACCOUNT_STYLES)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        title = QLabel("CONTAS NESTE PC")
        title.setObjectName("accountsHeading")
        heading.addWidget(title)
        heading.addStretch(1)
        self._count = self._pill("0 PERFIS", "muted")
        heading.addWidget(self._count)
        self._connection = self._pill("AGUARDANDO CLIENTE", "muted")
        heading.addWidget(self._connection)
        layout.addLayout(heading)

        overview = QFrame()
        overview.setObjectName("accountsOverview")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(14, 12, 14, 12)
        overview_layout.setSpacing(4)
        overview_title = QLabel("PERFIS, PREFERÊNCIAS E CONTROLES")
        overview_title.setObjectName("accountsListLabel")
        overview_layout.addWidget(overview_title)
        overview_note = QLabel(
            "Cada perfil conserva campeões, rotas, Flash e automações. "
            "A conta principal é a base para perfis novos; o modelo de "
            "controles do jogo acompanha essa escolha."
        )
        overview_note.setObjectName("accountsSummary")
        overview_note.setWordWrap(True)
        overview_layout.addWidget(overview_note)
        layout.addWidget(overview)

        list_heading = QHBoxLayout()
        list_title = QLabel("PERFIS SALVOS")
        list_title.setObjectName("accountsListLabel")
        list_heading.addWidget(list_title)
        list_heading.addStretch(1)
        self._model_status = QLabel()
        self._model_status.setObjectName("accountMeta")
        list_heading.addWidget(self._model_status)
        layout.addLayout(list_heading)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        layout.addLayout(self._rows)

        self._empty = QLabel(
            "Ainda não há perfis salvos. Abra o cliente do LoL: a primeira "
            "conta reconhecida será guardada como principal."
        )
        self._empty.setObjectName("accountsSummary")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(self._empty)

    def show_accounts(
        self,
        entries,
        active: str = "",
        main: str = "",
        connected: bool = False,
    ) -> None:
        """Redesenha a lista com o estado atual da conexão.

        A conta logada agora não pode ser esquecida: ela voltaria na volta
        seguinte do relógio e o botão pareceria defeituoso. O estado da
        conexão também fica explícito para deixar claro quando os botões de
        ler/aplicar controles podem agir.
        """
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = list(entries)
        count = len(entries)
        self._count.setText(f"{count} {'PERFIL' if count == 1 else 'PERFIS'}")
        self._connection.setText(
            "CLIENTE CONECTADO" if connected else "AGUARDANDO CLIENTE"
        )
        self._connection.setProperty("tone", "teal" if connected else "muted")
        self._refresh_style(self._connection)

        self._empty.setVisible(not entries)
        model = any(
            key == main and getattr(account, "game_settings", None)
            for key, account in entries
        )
        self._model_status.setText(
            "MODELO DO JOGO ATIVO" if model else "SEM MODELO DO JOGO"
        )
        for key, account in entries:
            self._rows.addWidget(
                self._row(key, account, active, main, model, connected)
            )

    def _row(
        self,
        key: str,
        account,
        active: str,
        main: str,
        model: bool = False,
        connected: bool = False,
    ) -> QWidget:
        saved = bool(getattr(account, "game_settings", None))
        state = "active-main" if key == active == main else (
            "active" if key == active else "main" if key == main else "saved"
        )

        row = QFrame()
        row.setObjectName("accountEntry")
        row.setProperty("state", state)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        content = QVBoxLayout(row)
        content.setContentsMargins(14, 12, 14, 11)
        content.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(8)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        label = QLabel(str(getattr(account, "label", "Conta sem nome")))
        label.setObjectName("accountName")
        identity.addWidget(label)
        metadata = QLabel(self._metadata(account))
        metadata.setObjectName("accountMeta")
        identity.addWidget(metadata)
        head.addLayout(identity, 1)

        badges = QHBoxLayout()
        badges.setSpacing(5)
        if key == main:
            badges.addWidget(self._pill("PRINCIPAL", "gold"))
        if key == active:
            badges.addWidget(self._pill("EM USO", "teal"))
        if saved:
            badges.addWidget(self._pill("MODELO DO JOGO", "blue"))
        head.addLayout(badges)
        content.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        actions.addStretch(1)
        if key != main:
            promote = self._action("Tornar principal", "primary")
            promote.setToolTip(
                "Usa este perfil como base para contas novas neste computador."
            )
            promote.clicked.connect(lambda _=False, k=key: self.main_requested.emit(k))
            actions.addWidget(promote)

        # As configurações de dentro do jogo só podem ser lidas e escritas
        # na conta que está conectada. Mostrar isso só na linha ativa reduz a
        # chance de clicar em uma ação que não tem como funcionar.
        if key == active:
            if key == main:
                capture = self._action(
                    "Atualizar controles" if saved else "Guardar controles",
                    "primary",
                )
                capture.setToolTip(
                    "Salva teclas, interface, câmera e minimapa como modelo."
                )
                self._requires_client(capture, connected)
                capture.clicked.connect(
                    lambda _=False, k=key: self.capture_requested.emit(k)
                )
                actions.addWidget(capture)
                if saved:
                    stop = self._action("Parar de copiar", "")
                    stop.setToolTip(
                        "Mantém os perfis, mas desliga a cópia automática no LoL."
                    )
                    stop.clicked.connect(
                        lambda _=False, k=key: self.clear_requested.emit(k)
                    )
                    actions.addWidget(stop)
            elif model:
                again = self._action("Aplicar controles agora", "primary")
                again.setToolTip(
                    "Reaplica o modelo da conta principal nesta conta conectada."
                )
                self._requires_client(again, connected)
                again.clicked.connect(
                    lambda _=False, k=key: self.apply_requested.emit(k)
                )
                actions.addWidget(again)

        forget = self._action("Remover", "danger")
        forget.setEnabled(key != active)
        forget.setToolTip(
            "A conta conectada não pode ser removida enquanto estiver em uso."
            if key == active
            else "Remove apenas este perfil salvo deste computador."
        )
        forget.clicked.connect(lambda _=False, k=key: self.forget_requested.emit(k))
        actions.addWidget(forget)
        content.addLayout(actions)
        return row

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        """Faz uma propriedade dinâmica aparecer sem recriar o cartão."""
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    @staticmethod
    def _pill(text: str, tone: str) -> QLabel:
        pill = QLabel(text)
        pill.setObjectName("accountPill")
        pill.setProperty("tone", tone)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return pill

    @staticmethod
    def _action(text: str, kind: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("accountAction")
        if kind:
            button.setProperty("kind", kind)
        return button

    @staticmethod
    def _requires_client(button: QPushButton, connected: bool) -> None:
        """Desativa operações da LCU quando não há ninguém para recebê-las."""
        if connected:
            return
        button.setEnabled(False)
        button.setToolTip("Abra o cliente do LoL para usar esta ação.")

    @staticmethod
    def _metadata(account) -> str:
        region = str(getattr(account, "region", "") or "").upper()
        place = f"Região {region}" if region else "Região não informada"
        seen = str(getattr(account, "last_seen", "") or "")
        return f"{place}  •  {_seen_label(seen)}"


def _seen_label(value: str) -> str:
    """Formata a data gravada sem deixar texto técnico vazar na tela."""
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "último acesso não registrado"
    return f"visto em {stamp:%d/%m/%Y às %H:%M}"
