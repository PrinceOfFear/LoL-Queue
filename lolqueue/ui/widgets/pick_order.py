"""A ordem de escolha, editável de dentro da Central de Fila.

Existe porque reordenar prioridade era coisa de outra página: no meio
de uma seleção de campeões, com o relógio correndo, trocar de tela para
arrastar um nome e voltar não dá tempo. Aqui a mesma lista fica ao lado
do boneco previsto, e o que muda aqui é o que a partida usa.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .champion_picker import PriorityList

ROW_ICON = QSize(22, 22)
#: O primeiro da lista é o que vai ser travado. Pintado à parte para
#: que a ordem se leia de relance, sem contar as linhas. Vai em código
#: e não no QSS: pseudo-estado de posição não vale para item de lista.
TOP_COLOR = QColor("#7FE8DF")
#: Cabe quatro linhas sem rolagem — o que a lista de prioridade costuma
#: ter — e não empurra o cartão de registro para fora da janela pequena.
LIST_HEIGHT = 132


class PickOrderPanel(QFrame):
    """Lista de prioridade compacta, com arrasto e setas.

    As setas existem ao lado do arrasto de propósito: durante a seleção
    a mão está com pressa, e um clique não erra o alvo como um arrasto
    curto erra.
    """

    #: A nova ordem, já na posição final. Quem grava é a janela.
    reordered = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("orderCard")
        self._name_of = None
        self._icon_of = None
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 11)
        layout.setSpacing(6)

        title = QLabel("ORDEM DE ESCOLHA")
        title.setObjectName("predictionEyebrow")
        layout.addWidget(title)

        #: Diz qual das listas está à vista — a geral ou a da rota que o
        #: cliente atribuiu. Sem isso dava para reordenar com capricho a
        #: lista errada e ver outro campeão ser escolhido.
        self._scope = QLabel()
        self._scope.setObjectName("orderScope")
        self._scope.setWordWrap(True)
        layout.addWidget(self._scope)

        self._list = PriorityList()
        self._list.setObjectName("orderList")
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setIconSize(ROW_ICON)
        self._list.setFixedHeight(LIST_HEIGHT)
        self._list.dropped.connect(self._on_dropped)
        # As setas só servem para a linha marcada; sem escutar a troca
        # de seleção elas ficariam desligadas até o próximo arrasto.
        self._list.currentRowChanged.connect(lambda _: self._refresh_state())
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        self._up = QPushButton("▲  subir")
        self._up.setObjectName("orderButton")
        self._up.clicked.connect(lambda: self._move(-1))
        buttons.addWidget(self._up)
        self._down = QPushButton("▼  descer")
        self._down.setObjectName("orderButton")
        self._down.clicked.connect(lambda: self._move(1))
        buttons.addWidget(self._down)
        layout.addLayout(buttons)

    # ---------- entrada de dados ----------

    def set_resolvers(self, name_of, icon_of) -> None:
        """Liga quem traduz id em nome e em caminho de retrato."""
        self._name_of = name_of
        self._icon_of = icon_of
        self._draw()

    def set_scope(self, label: str) -> None:
        self._scope.setText(label)

    def set_order(self, ids) -> None:
        """Redesenha a lista, se ela for mesmo outra.

        Comparar antes não é economia: a janela reescreve a Central a
        cada gravação, inclusive a que veio deste painel, e redesenhar
        ali derrubaria a seleção da linha que o usuário acabou de mover.
        """
        ids = [int(champion_id) for champion_id in ids]
        if ids == self._ids:
            return
        self._ids = ids
        self._draw()

    def ids(self) -> list[int]:
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
        ]

    # ---------- desenho ----------

    def _name(self, champion_id: int) -> str:
        if self._name_of is None:
            return f"#{champion_id}"
        return self._name_of(champion_id) or f"#{champion_id}"

    def _icon(self, champion_id: int) -> QIcon:
        path = None if self._icon_of is None else self._icon_of(champion_id)
        return QIcon(path) if path else QIcon()

    def _draw(self) -> None:
        self._list.clear()
        for position, champion_id in enumerate(self._ids, start=1):
            item = QListWidgetItem(f"{position}.  {self._name(champion_id)}")
            item.setData(Qt.ItemDataRole.UserRole, champion_id)
            item.setIcon(self._icon(champion_id))
            self._list.addItem(item)
        self._paint_top()
        self._refresh_state()

    def _paint_top(self) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            font = QFont(item.font())
            font.setBold(row == 0)
            item.setFont(font)
            if row == 0:
                item.setForeground(QBrush(TOP_COLOR))
            else:
                # `QBrush()` vazio devolve a linha à cor da folha de
                # estilo; deixar a cor antiga pintaria dois primeiros.
                item.setForeground(QBrush())

    def _refresh_state(self) -> None:
        """Mostra o aviso de lista vazia e liga as setas só quando servem."""
        vazia = not self._ids
        if vazia:
            self._list.setToolTip(
                "Sem campeão na lista. Escolha os seus na página Campeões."
            )
        else:
            self._list.setToolTip("Arraste, ou use as setas: o primeiro é o escolhido.")
        row = self._list.currentRow()
        self._up.setEnabled(row > 0)
        self._down.setEnabled(0 <= row < self._list.count() - 1)

    # ---------- interação ----------

    def _move(self, step: int) -> None:
        row = self._list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)
        self._commit()

    def _on_dropped(self, *_) -> None:
        self._commit()

    def _commit(self) -> None:
        self._ids = self.ids()
        # Só os rótulos mudam de número; redesenhar tudo apagaria a
        # linha selecionada, que é justamente a que se quer mover de novo.
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setText(f"{row + 1}.  {self._name(item.data(Qt.ItemDataRole.UserRole))}")
        self._paint_top()
        self._refresh_state()
        self.reordered.emit(list(self._ids))
