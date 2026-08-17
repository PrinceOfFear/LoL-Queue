from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

GRID_ICON = QSize(46, 46)
GRID_CELL = QSize(58, 58)
CHOSEN_ICON = QSize(30, 30)
CHOSEN_HEIGHT = 132


class PriorityList(QListWidget):
    """Lista arrastável que avisa quando um arrasto termina.

    Escutar `rowsMoved` não bastava: esse sinal só vem se o Qt resolver o
    arrasto interno como movimento de linha, e quando ele resolve por
    remoção e inserção nada é emitido. A reordenação ficava só na tela,
    a config guardava a ordem antiga e o motor escolhia por ela — foi o
    defeito relatado, com o campeão do topo antigo sendo escolhido de
    novo. `dropEvent` é o único ponto por onde todo drop passa.
    """

    dropped = Signal()

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.dropped.emit()


class ChampionPicker(QWidget):
    """Grade de retratos em cima, lista de prioridade embaixo.

    Clicar num retrato acrescenta o campeão ao fim da lista. A posição na
    lista é a prioridade: o primeiro é tentado primeiro e, se estiver
    indisponível, desce para o próximo. Arrastar reordena.
    """

    changed = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = None
        self._icons = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self._search = QLineEdit()
        self._search.setObjectName("search")
        self._search.setPlaceholderText("buscar campeão")
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
        self._grid.itemClicked.connect(self._add)
        layout.addWidget(self._grid, 1)

        self._layout = layout
        self._chosen_label = QLabel("ESCOLHIDOS — ARRASTE PARA REORDENAR")
        self._chosen_label.setObjectName("subTitle")
        layout.addWidget(self._chosen_label)

        self._list = PriorityList()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setIconSize(CHOSEN_ICON)
        self._list.setFixedHeight(CHOSEN_HEIGHT)
        self._list.dropped.connect(self._on_reordered)
        layout.addWidget(self._list)

        remove = QPushButton("Remover selecionado")
        remove.setObjectName("logToggle")
        remove.clicked.connect(self._remove_selected)
        layout.addWidget(remove)

    def add_list_header(self, widget: QWidget) -> None:
        """Encaixa um widget logo acima da lista de prioridade.

        É por aqui que a seleção por rota pendura suas abas, sem que a
        grade precise saber que rotas existem.
        """
        self._layout.insertWidget(self._layout.indexOf(self._chosen_label), widget)

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
        """Descarta escolhas que o catálogo não reconhece.

        Um id inexistente jamais seria escolhido — ficaria só ocupando
        uma posição da prioridade, parecendo válido. Só age com o
        catálogo carregado: numa falha de rede ele está vazio, e podar
        por ele apagaria tudo que o usuário escolheu.
        """
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
        self._list.clear()
        for champion_id in ids:
            self._append(champion_id)

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
            # Na primeira execução os retratos ainda estão vindo. Sem o
            # nome no lugar, a grade seria um campo de quadrados vazios.
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
        """Reescreve os rótulos: a posição na lista é a prioridade."""
        for row in range(self._list.count()):
            item = self._list.item(row)
            champion_id = item.data(Qt.ItemDataRole.UserRole)
            item.setText(self._label(row + 1, champion_id))
            icon = self._icon(champion_id)
            item.setIcon(icon if icon is not None else QIcon())

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
        self._emit()

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
        self._renumber()
        self._emit()

    def _on_reordered(self, *_) -> None:
        self._renumber()
        self._emit()

    def _emit(self) -> None:
        self.changed.emit(self.ids())
