from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ChampionPicker(QWidget):
    """Lista ordenada de campeões por prioridade.

    O primeiro da lista é tentado primeiro; se estiver indisponível,
    desce para o próximo.
    """

    changed = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        row.addWidget(self._combo, 1)
        add = QPushButton("Adicionar")
        add.setObjectName("primaryButton")
        add.clicked.connect(self._add_selected)
        row.addWidget(add)
        layout.addLayout(row)

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setFixedHeight(150)
        self._list.model().rowsMoved.connect(self._on_reordered)
        layout.addWidget(self._list)

        remove = QPushButton("Remover selecionado")
        remove.setObjectName("logToggle")
        remove.clicked.connect(self._remove_selected)
        layout.addWidget(remove)

    def set_catalog(self, catalog) -> None:
        self._catalog = catalog
        self._combo.clear()
        for champion_id, name in catalog.all():
            self._combo.addItem(name, champion_id)

    def set_ids(self, ids: list[int]) -> None:
        self._list.clear()
        for champion_id in ids:
            self._append(champion_id)

    def ids(self) -> list[int]:
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
        ]

    def _label(self, position: int, champion_id: int) -> str:
        name = self._catalog.name(champion_id) if self._catalog else f"#{champion_id}"
        return f"{position}.  {name}"

    def _append(self, champion_id: int) -> None:
        item = QListWidgetItem(self._label(self._list.count() + 1, champion_id))
        item.setData(Qt.ItemDataRole.UserRole, champion_id)
        self._list.addItem(item)

    def _renumber(self) -> None:
        """Reescreve os rótulos: a posição na lista é a prioridade."""
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setText(self._label(row + 1, item.data(Qt.ItemDataRole.UserRole)))

    def _on_reordered(self, *_) -> None:
        self._renumber()
        self._emit()

    def _add_selected(self) -> None:
        champion_id = self._combo.currentData()
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

    def _emit(self) -> None:
        self.changed.emit(self.ids())
