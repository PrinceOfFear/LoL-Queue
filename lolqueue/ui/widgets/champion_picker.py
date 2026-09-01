from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)


# A grade continua compacta o suficiente para a lista inteira caber na tela,
# mas os retratos agora respiram e ficam legíveis sem aproximar o rosto.
GRID_ICON = QSize(50, 50)
GRID_CELL = QSize(62, 62)
CHOSEN_ICON = QSize(36, 36)
PRIORITY_ROW_HEIGHT = 46
PRIORITY_MIN_HEIGHT = 76
PRIORITY_MAX_HEIGHT = 166
PRIORITY_FIRST_COLOR = QColor("#86EEE2")


# Este QSS mora no próprio componente para a reforma da tela Campeões não
# alterar listas, abas e botões de outras páginas. A janela ainda fornece as
# fontes e a paleta geral; aqui entram só os detalhes da interação.
PICKER_STYLES = """
#championPicker {
    background: transparent;
}
#championLibraryLabel, #priorityLabel {
    color: #86AFCB;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.25px;
}
#championCount {
    background: rgba(10, 200, 185, 22);
    border: 1px solid rgba(70, 202, 190, 108);
    border-radius: 8px;
    color: #91EEE6;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 4px 7px;
}
#championCount[empty="true"] {
    background: rgba(117, 145, 171, 15);
    border-color: rgba(117, 145, 171, 68);
    color: #8DA2B4;
}
#championGrid {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(5, 21, 40, 194), stop:1 rgba(3, 14, 29, 180));
    border: 1px solid rgba(88, 139, 179, 112);
    border-radius: 10px;
    padding: 4px;
}
#championGrid::item {
    background: rgba(9, 29, 51, 120);
    border: 1px solid rgba(116, 166, 202, 35);
    border-radius: 7px;
    padding: 3px;
    font-size: 8px;
    color: #B4C8D6;
}
#championGrid::item:hover {
    background: rgba(19, 112, 124, 126);
    border-color: rgba(112, 235, 222, 160);
}
#championPriorityHost {
    background: rgba(3, 15, 30, 178);
    border: 1px solid rgba(86, 136, 176, 112);
    border-radius: 10px;
}
#championPriorityList {
    background: transparent;
    border: none;
    outline: none;
    font-size: 12px;
}
#championPriorityList::item {
    background: rgba(21, 51, 78, 100);
    border: 1px solid rgba(111, 159, 195, 48);
    border-radius: 7px;
    color: #E4EDF3;
    margin: 3px 5px;
    padding: 4px 9px;
}
#championPriorityList::item:hover {
    background: rgba(31, 83, 105, 158);
    border-color: rgba(115, 222, 213, 134);
}
#championPriorityList::item:selected {
    background: rgba(10, 144, 150, 108);
    border-color: rgba(109, 239, 228, 192);
    color: #FFF3D1;
}
#championPriorityEmpty {
    background: qradialgradient(cx:.5, cy:.42, radius:.75,
        stop:0 rgba(10, 200, 185, 19), stop:1 rgba(3, 15, 30, 0));
    border: none;
    color: #90AABD;
    font-size: 11px;
    font-weight: 600;
    line-height: 1.35;
    padding: 10px 18px;
}
#priorityHint {
    color: #AABFCE;
    font-size: 10px;
    font-weight: 600;
}
#priorityAction, #priorityRemove {
    background: rgba(27, 61, 91, 158);
    border: 1px solid rgba(120, 170, 205, 102);
    border-radius: 8px;
    color: #DCEAF2;
    font-size: 10px;
    font-weight: 800;
    padding: 7px 10px;
}
#priorityAction:hover {
    background: rgba(13, 122, 130, 132);
    border-color: rgba(105, 234, 222, 180);
    color: #F1FFFC;
}
#priorityRemove:hover {
    background: rgba(151, 49, 65, 132);
    border-color: rgba(243, 126, 140, 178);
    color: #FFE4E8;
}
#priorityAction:disabled, #priorityRemove:disabled {
    background: rgba(21, 40, 58, 94);
    border-color: rgba(91, 119, 144, 52);
    color: #647B8E;
}
#listNotice {
    background: rgba(13, 74, 90, 46);
    border: 1px solid rgba(70, 176, 177, 74);
    border-radius: 7px;
    color: #B7D4DD;
    font-size: 10px;
    padding: 6px 9px;
}
#listNotice[alert="true"] {
    background: rgba(126, 92, 31, 46);
    border-color: rgba(224, 181, 97, 92);
    color: #F0D79D;
}
"""


class PriorityList(QListWidget):
    """Lista arrastável que avisa quando um arrasto termina.

    Escutar ``rowsMoved`` não bastava: esse sinal só vem se o Qt resolver o
    arrasto interno como movimento de linha, e quando ele resolve por
    remoção e inserção nada é emitido. A reordenação ficava só na tela,
    a config guardava a ordem antiga e o motor escolhia por ela.
    ``dropEvent`` é o único ponto por onde todo drop passa.
    """

    dropped = Signal()

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.dropped.emit()


class ChampionPicker(QWidget):
    """Biblioteca de retratos e uma prioridade realmente fácil de editar.

    O primeiro campeão da lista é tentado primeiro. Além do arrasto, as
    setas deixam a troca de posição previsível em trackpad, telas pequenas e
    durante a pressa da seleção de campeões.
    """

    changed = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("championPicker")
        self.setStyleSheet(PICKER_STYLES)
        self._catalog = None
        self._icons = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        # Título, estado e automação ficam na mesma linha: não há como montar
        # uma lista sem enxergar se ela tem campeões e se o automático vale.
        self._head = QHBoxLayout()
        self._head.setContentsMargins(0, 0, 0, 0)
        self._head.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        self._head.addWidget(heading)
        self._head.addStretch(1)
        layout.addLayout(self._head)

        #: Onde ``add_header`` encaixa o próximo widget: logo depois do
        #: título. A seleção por rota precisa vir antes da grade que ela muda.
        self._header_slot = layout.count()

        self._notice = QLabel()
        self._notice.setObjectName("listNotice")
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)

        library = QLabel("BIBLIOTECA  ·  CLIQUE PARA ADICIONAR")
        library.setObjectName("championLibraryLabel")
        layout.addWidget(library)

        self._search = QLineEdit()
        self._search.setObjectName("search")
        self._search.setPlaceholderText("Buscar campeão por nome…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        self._grid = QListWidget()
        self._grid.setObjectName("championGrid")
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setIconSize(GRID_ICON)
        self._grid.setGridSize(GRID_CELL)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._grid.setUniformItemSizes(True)
        self._grid.setWordWrap(False)
        self._grid.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # A biblioteca recalcula o número de colunas conforme a largura
        # disponível. Sem esta política o QListWidget guarda como largura
        # mínima a grade inteira que conheceu primeiro e força a página
        # Campeões a ultrapassar janelas menores, mesmo podendo quebrar os
        # retratos em mais linhas sem perder nada.
        self._grid.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self._grid.setMinimumWidth(0)
        self._grid.itemClicked.connect(self._add)
        layout.addWidget(self._grid, 1)

        priority_head = QHBoxLayout()
        priority_head.setContentsMargins(0, 2, 0, 0)
        priority_head.setSpacing(8)
        self._chosen_label = QLabel("SUA ORDEM DE PRIORIDADE")
        self._chosen_label.setObjectName("priorityLabel")
        self._chosen_label.setToolTip(
            "O campeão nº 1 é tentado primeiro. Selecione uma linha e use "
            "Subir/Descer, ou arraste, para mudar a ordem."
        )
        priority_head.addWidget(self._chosen_label)
        priority_head.addStretch(1)
        # A contagem pertence à ordem que ela resume. Antes ela dividia a
        # mesma faixa do título e do interruptor automático, impondo uma
        # largura mínima grande demais às duas colunas da página.
        self._count_badge = QLabel()
        self._count_badge.setObjectName("championCount")
        priority_head.addWidget(self._count_badge)
        layout.addLayout(priority_head)

        self._priority_host = QFrame()
        self._priority_host.setObjectName("championPriorityHost")
        self._priority_stack = QStackedLayout(self._priority_host)
        self._priority_stack.setContentsMargins(0, 0, 0, 0)

        self._empty_priority = QLabel(
            "Sua lista está vazia.\nClique nos retratos acima para definir quem entra primeiro."
        )
        self._empty_priority.setObjectName("championPriorityEmpty")
        self._empty_priority.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_priority.setWordWrap(True)
        self._priority_stack.addWidget(self._empty_priority)

        self._list = PriorityList()
        self._list.setObjectName("championPriorityList")
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setIconSize(CHOSEN_ICON)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setToolTip(
            "Selecione um campeão e use as setas, ou arraste para mudar a prioridade."
        )
        self._list.dropped.connect(self._on_reordered)
        self._list.currentRowChanged.connect(
            lambda _: self._refresh_priority_presentation()
        )
        self._priority_stack.addWidget(self._list)
        layout.addWidget(self._priority_host)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(7)
        self._up_button = QPushButton("↑  Subir")
        self._up_button.setObjectName("priorityAction")
        self._up_button.setToolTip(
            "Move o campeão selecionado uma posição para cima."
        )
        self._up_button.clicked.connect(lambda: self._move_selected(-1))
        actions.addWidget(self._up_button)
        self._down_button = QPushButton("↓  Descer")
        self._down_button.setObjectName("priorityAction")
        self._down_button.setToolTip(
            "Move o campeão selecionado uma posição para baixo."
        )
        self._down_button.clicked.connect(lambda: self._move_selected(1))
        actions.addWidget(self._down_button)
        actions.addStretch(1)
        self._remove_button = QPushButton("Remover")
        self._remove_button.setObjectName("priorityRemove")
        self._remove_button.setToolTip("Remove o campeão selecionado desta lista.")
        self._remove_button.clicked.connect(self._remove_selected)
        actions.addWidget(self._remove_button)
        layout.addLayout(actions)

        self._layout = layout
        self._refresh_priority_presentation()

    def add_header(self, widget: QWidget) -> None:
        """Encaixa um widget logo abaixo do título, antes do aviso e da grade."""
        self._layout.insertWidget(self._header_slot, widget)
        self._header_slot += 1

    def set_title_widget(self, widget: QWidget) -> None:
        """Encosta um widget à direita do título desta lista."""
        self._head.addWidget(widget)

    def set_notice(self, text: str, alert: bool = False) -> None:
        """Escreve o aviso desta lista; ``alert`` é o que muda a cor."""
        self._notice.setText(text)
        self._notice.setProperty("alert", alert)
        self._repolish(self._notice)

    def notice(self) -> str:
        return self._notice.text()

    # ---------- entrada de dados ----------

    def set_catalog(self, catalog) -> None:
        self._catalog = catalog
        self._grid.clear()
        for champion_id, _ in catalog.all():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, champion_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._decorate(item, champion_id)
            self._grid.addItem(item)
        self._prune()
        # A lista de prioridade pode ter vindo da config antes do catálogo;
        # sem isto os salvos ficariam exibidos como "#64".
        self._renumber()
        self._filter(self._search.text())

    def _prune(self) -> None:
        """Descarta escolhas que o catálogo não reconhece, quando ele existe."""
        if self._catalog is None or not self._catalog.loaded:
            return
        current = self.ids()
        kept = [champion_id for champion_id in current if self._catalog.knows(champion_id)]
        if kept == current:
            return
        self.set_ids(kept)
        self._emit()

    def set_icons(self, store) -> None:
        """Liga (ou religa) o cache de retratos e redesenha o que houver."""
        self._icons = store
        for row in range(self._grid.count()):
            item = self._grid.item(row)
            self._decorate(item, item.data(Qt.ItemDataRole.UserRole))
        self._renumber()

    def set_ids(self, ids: list[int]) -> None:
        """Carrega uma lista sem tratá-la como uma edição do usuário."""
        self._list.clear()
        for champion_id in ids:
            self._append(champion_id)
        self._list.setCurrentRow(-1)
        self._renumber()

    def ids(self) -> list[int]:
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
        ]

    # ---------- desenho ----------

    def _name(self, champion_id: int) -> str:
        if self._catalog is None:
            return f"#{champion_id}"
        return self._catalog.name(champion_id)

    def _icon(self, champion_id: int) -> QIcon | None:
        if self._icons is None or not self._icons.has(champion_id):
            return None
        return QIcon(str(self._icons.path_for(champion_id)))

    def _decorate(self, item: QListWidgetItem, champion_id: int) -> None:
        """Retrato quando existe; nome enquanto ainda está baixando."""
        name = self._name(champion_id)
        item.setToolTip(name)
        icon = self._icon(champion_id)
        if icon is None:
            # Na primeira execução os retratos ainda estão vindo. Sem o nome
            # no lugar, a grade seria um campo de quadrados vazios.
            item.setText(name)
            item.setIcon(QIcon())
        else:
            item.setText("")
            item.setIcon(icon)

    def _label(self, position: int, champion_id: int) -> str:
        return f"{position}.  {self._name(champion_id)}"

    def _append(self, champion_id: int) -> None:
        item = QListWidgetItem(self._label(self._list.count() + 1, champion_id))
        item.setData(Qt.ItemDataRole.UserRole, champion_id)
        icon = self._icon(champion_id)
        if icon is not None:
            item.setIcon(icon)
        self._list.addItem(item)

    def _renumber(self) -> None:
        """Reescreve rótulos e deixa o campeão prioritário evidente."""
        for row in range(self._list.count()):
            item = self._list.item(row)
            champion_id = item.data(Qt.ItemDataRole.UserRole)
            item.setText(self._label(row + 1, champion_id))
            item.setToolTip(f"Prioridade {row + 1}: {self._name(champion_id)}")
            item.setSizeHint(QSize(0, PRIORITY_ROW_HEIGHT))
            icon = self._icon(champion_id)
            item.setIcon(icon if icon is not None else QIcon())

            font = QFont(item.font())
            font.setBold(row == 0)
            item.setFont(font)
            item.setForeground(QBrush(PRIORITY_FIRST_COLOR) if row == 0 else QBrush())
        self._refresh_priority_presentation()

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        """Aplica logo a cor de uma propriedade dinâmica do QSS."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _refresh_priority_presentation(self) -> None:
        """Sincroniza vazio, contagem, altura e controles com a lista real."""
        count = self._list.count()
        empty = count == 0
        self._count_badge.setText(
            "LISTA VAZIA" if empty else f"{count} CAMPEÃO" + ("" if count == 1 else "ES")
        )
        self._count_badge.setProperty("empty", empty)
        self._repolish(self._count_badge)

        if empty:
            self._priority_stack.setCurrentWidget(self._empty_priority)
        else:
            self._priority_stack.setCurrentWidget(self._list)

        # Um campeão não ganha uma caixa enorme vazia; listas maiores crescem
        # até três linhas e depois usam a própria rolagem.
        visible_rows = max(1, min(count, 3))
        height = max(PRIORITY_MIN_HEIGHT, visible_rows * PRIORITY_ROW_HEIGHT + 10)
        self._priority_host.setFixedHeight(min(height, PRIORITY_MAX_HEIGHT))

        row = self._list.currentRow()
        self._up_button.setEnabled(row > 0)
        self._down_button.setEnabled(0 <= row < count - 1)
        self._remove_button.setEnabled(0 <= row < count)

    # ---------- interação ----------

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self._grid.count()):
            item = self._grid.item(row)
            item.setHidden(bool(needle) and needle not in item.toolTip().casefold())

    def _add(self, item: QListWidgetItem) -> None:
        champion_id = item.data(Qt.ItemDataRole.UserRole)
        if champion_id is None or champion_id in self.ids():
            return
        self._append(champion_id)
        self._list.setCurrentRow(self._list.count() - 1)
        self._renumber()
        self._emit()

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
        if self._list.count():
            self._list.setCurrentRow(min(row, self._list.count() - 1))
        self._renumber()
        self._emit()

    def _move_selected(self, step: int) -> None:
        """Move a linha marcada sem exigir precisão de arrasto."""
        row = self._list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)
        self._renumber()
        self._emit()

    def _on_reordered(self, *_) -> None:
        self._renumber()
        self._emit()

    def _emit(self) -> None:
        self.changed.emit(self.ids())
