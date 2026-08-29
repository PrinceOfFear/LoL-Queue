"""O histórico de contas, e qual delas manda nas outras.

A lista é curta por natureza — são as contas que entraram neste PC —,
então ela é redesenhada inteira a cada mudança em vez de ganhar um
modelo. Redesenhar uma dúzia de linhas custa menos do que manter dois
estados em acordo.

O cartão não sabe ler nem gravar nada: recebe as contas prontas e avisa
por sinal quando o usuário pede algo. Quem decide é a janela, que é
quem tem o arquivo e a config.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AccountsCard(QFrame):
    """As contas lembradas, com o posto de principal em disputa."""

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
        self.setObjectName("settingsCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(7)

        title = QLabel("CONTAS NESTE PC")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        note = QLabel(
            "Cada conta guarda os próprios ajustes — lista de campeões, "
            "rotas pedidas, tecla do Flash, tempos. Ao entrar em uma delas, "
            "o app volta a ser o que era naquela conta. Uma conta que nunca "
            "entrou aqui começa com tudo o que está na principal, que é o "
            "que se quer ao jogar na conta de outra pessoa: o seu app, na "
            "conta dela."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        game = QLabel(
            "Com a conta principal logada, “Guardar config do jogo” tira "
            "uma cópia das configurações de dentro do LoL — teclas das "
            "habilidades, dos feitiços de invocador e dos itens, "
            "movimentação, interface, câmera e minimapa. Toda conta que "
            "entrar depois recebe essas configurações sozinha, alguns "
            "segundos após o login. Qualidade gráfica e modo de vídeo "
            "ficam de fora: são do computador, não de quem joga."
        )
        game.setObjectName("hint")
        game.setWordWrap(True)
        layout.addWidget(game)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 4, 0, 0)
        self._rows.setSpacing(5)
        layout.addLayout(self._rows)

        self._empty = QLabel(
            "Nenhuma conta ainda. A primeira que entrar com o cliente do "
            "LoL aberto vira a principal."
        )
        self._empty.setObjectName("hint")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

    def show_accounts(self, entries, active: str = "", main: str = "") -> None:
        """Redesenha a lista. `entries` são pares (chave, conta).

        A conta logada agora não pode ser esquecida: ela voltaria na
        volta seguinte do relógio, e o botão pareceria quebrado.
        """
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = list(entries)
        self._empty.setVisible(not entries)
        model = any(
            key == main and getattr(account, "game_settings", None)
            for key, account in entries
        )
        for key, account in entries:
            self._rows.addWidget(self._row(key, account, active, main, model))

    def _row(
        self, key: str, account, active: str, main: str, model: bool = False
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("optionCard")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 8, 14, 8)
        line.setSpacing(9)

        saved = bool(getattr(account, "game_settings", None))
        marks = []
        if key == main:
            marks.append("principal")
        if key == active:
            marks.append("logada agora")
        if saved:
            marks.append("config do jogo guardada")
        label = QLabel(account.label + (f"  ·  {', '.join(marks)}" if marks else ""))
        label.setObjectName("cardLabel")
        line.addWidget(label)
        line.addStretch(1)

        if key != main:
            promote = QPushButton("Tornar principal")
            promote.setObjectName("orderButton")
            promote.clicked.connect(lambda _=False, k=key: self.main_requested.emit(k))
            line.addWidget(promote)

        # As configurações de dentro do jogo só podem ser lidas e
        # escritas na conta que está logada — é a única que o cliente do
        # LoL tem na mão. Por isso os botões só aparecem nessa linha.
        if key == active:
            if key == main:
                capture = QPushButton(
                    "Atualizar config do jogo" if saved else "Guardar config do jogo"
                )
                capture.setObjectName("orderButton")
                capture.clicked.connect(
                    lambda _=False, k=key: self.capture_requested.emit(k)
                )
                line.addWidget(capture)
                if saved:
                    stop = QPushButton("Parar de copiar")
                    stop.setObjectName("orderButton")
                    stop.clicked.connect(
                        lambda _=False, k=key: self.clear_requested.emit(k)
                    )
                    line.addWidget(stop)
            elif model:
                # Rede de segurança para quando o cliente termina de
                # carregar a conta depois da cópia automática e escreve
                # por cima dela.
                again = QPushButton("Aplicar config do jogo")
                again.setObjectName("orderButton")
                again.clicked.connect(
                    lambda _=False, k=key: self.apply_requested.emit(k)
                )
                line.addWidget(again)

        forget = QPushButton("Esquecer")
        forget.setObjectName("orderButton")
        forget.setEnabled(key != active)
        forget.clicked.connect(lambda _=False, k=key: self.forget_requested.emit(k))
        line.addWidget(forget)
        return row
