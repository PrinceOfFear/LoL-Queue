"""Fiação da lista de prioridade.

A ordem da lista é a prioridade de escolha, então toda mudança precisa
sair daqui como sinal — uma reordenação que não é reportada fica só na
tela e o motor segue escolhendo pela ordem antiga.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.ui.widgets.champion_picker import ChampionPicker  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def picker(app):
    picker = ChampionPicker("ESCOLHA")
    picker.set_ids([64, 11, 12])
    return picker


def drop_on(widget, row):
    """Solta o que está sendo arrastado sobre a linha indicada."""
    model = widget.model()
    event = QtGui.QDropEvent(
        QtCore.QPointF(widget.visualRect(model.index(row, 0)).topLeft()),
        QtCore.Qt.DropAction.MoveAction,
        model.mimeData([model.index(widget.currentRow(), 0)]),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)


def test_a_drop_always_reports_the_order(picker):
    """O arrasto tem que reportar, seja como o Qt resolver mover a linha.

    A versão anterior escutava `rowsMoved`, que depende de o Qt tratar o
    arrasto interno como movimento — quando ele resolve por remoção e
    inserção, o sinal nunca vem. A reordenação ficava só na tela e o
    motor continuava escolhendo pela ordem antiga, que foi o defeito
    relatado. `dropEvent` é o ponto por onde todo drop passa.
    """
    seen = []
    picker.changed.connect(lambda ids: seen.append(list(ids)))

    picker._list.setCurrentRow(2)
    drop_on(picker._list, 0)

    assert seen == [picker.ids()]


def test_clicking_a_portrait_reports_the_new_list(picker):
    seen = []
    picker.changed.connect(lambda ids: seen.append(list(ids)))

    item = QtWidgets.QListWidgetItem()
    item.setData(QtCore.Qt.ItemDataRole.UserRole, 99)
    picker._add(item)

    assert seen == [[64, 11, 12, 99]]


def test_removing_reports_the_new_list(picker):
    seen = []
    picker.changed.connect(lambda ids: seen.append(list(ids)))

    picker._list.setCurrentRow(1)
    picker._remove_selected()

    assert seen == [[64, 12]]


def test_the_labels_number_the_priority(picker):
    """A posição é a prioridade, então ela precisa estar escrita."""
    labels = [picker._list.item(row).text() for row in range(3)]

    assert labels[0].startswith("1.")
    assert labels[2].startswith("3.")


def test_loading_a_list_does_not_report_it_back(picker):
    """Trocar de aba carrega a lista da rota; carregar não é editar.

    Se `set_ids` reportasse, abrir uma aba gravaria o conteúdo dela por
    cima da lista que o usuário acabou de mexer.
    """
    seen = []
    picker.changed.connect(lambda ids: seen.append(list(ids)))

    picker.set_ids([21, 202])

    assert seen == []


def test_priority_buttons_move_the_selected_champion_without_dragging(picker):
    """Setas deixam mudar posição sem a precisão frágil de um arrasto."""
    seen = []
    picker.changed.connect(lambda ids: seen.append(list(ids)))

    picker._list.setCurrentRow(2)
    picker._move_selected(-1)

    assert picker.ids() == [64, 12, 11]
    assert picker._list.currentRow() == 1
    assert seen == [[64, 12, 11]]


def test_priority_buttons_only_enable_when_their_move_is_possible(picker):
    """Não há botão que pareça quebrado no topo, no meio ou no fim."""
    assert not picker._up_button.isEnabled()
    assert not picker._down_button.isEnabled()
    assert not picker._remove_button.isEnabled()

    picker._list.setCurrentRow(0)
    assert not picker._up_button.isEnabled()
    assert picker._down_button.isEnabled()
    assert picker._remove_button.isEnabled()

    picker._list.setCurrentRow(2)
    assert picker._up_button.isEnabled()
    assert not picker._down_button.isEnabled()


def test_an_empty_priority_explains_how_to_start(app):
    picker = ChampionPicker("ESCOLHA")

    assert picker._priority_stack.currentWidget() is picker._empty_priority
    assert "Clique nos retratos" in picker._empty_priority.text()
    assert picker._count_badge.text() == "LISTA VAZIA"
