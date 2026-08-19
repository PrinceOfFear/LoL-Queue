from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabBar, QVBoxLayout, QWidget

from ...config import POSITIONS, position_name
from ..advice import GENERAL, TAB_LABELS, TAB_ORDER, join_names, pick_notice
from .champion_picker import ChampionPicker

__all__ = [
    "GENERAL",
    "TAB_LABELS",
    "TAB_ORDER",
    "PositionPicker",
    "join_names",
]

#: Marca as abas que têm lista própria, para dar de relance quais rotas
#: estão configuradas e quais caem na geral.
FILLED_MARK = " ●"


class PositionPicker(QWidget):
    """Uma lista de prioridade por rota, sobre uma grade só.

    As abas trocam qual lista está sendo editada. Rota sem lista própria
    usa a geral na hora de escolher — inclusive quando o jogador cai de
    autofill numa rota que nunca configurou.
    """

    #: (chave da rota, ids). A chave vazia é a lista geral.
    changed = Signal(str, list)

    def __init__(
        self,
        title: str,
        general: list[int],
        by_position: dict[str, list[int]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._lists: dict[str, list[int]] = {GENERAL: list(general)}
        for position in POSITIONS:
            self._lists[position] = list(by_position.get(position) or [])
        self._current = GENERAL
        #: Começa ligada para que o aviso não acuse desligamento antes de
        #: a janela dizer como a config está de fato.
        self._automatic = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._picker = ChampionPicker(title)
        layout.addWidget(self._picker)

        self._tabs = QTabBar()
        self._tabs.setObjectName("positionTabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        for key in TAB_ORDER:
            index = self._tabs.addTab(TAB_LABELS[key])
            self._tabs.setTabToolTip(index, self._tooltip(key))
        self._picker.add_header(self._tabs)

        self._picker.set_ids(self._lists[GENERAL])
        self._refresh_marks()
        self._refresh_notice()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._picker.changed.connect(self._on_ids_changed)

    # ---------- repasse para a grade ----------

    def set_catalog(self, catalog) -> None:
        """Poda todas as listas, não só a que está à vista.

        A grade só conhece a lista aberta; sem podar as outras aqui, um
        id que o catálogo não reconhece sobreviveria escondido numa aba
        fechada e nunca seria escolhido.
        """
        if catalog is not None and catalog.loaded:
            for key, ids in self._lists.items():
                kept = [c for c in ids if catalog.knows(c)]
                if kept != ids:
                    self._lists[key] = kept
                    self.changed.emit(key, kept)
            self._picker.set_ids(self._lists[self._current])
            self._refresh_marks()
            self._refresh_notice()
        self._picker.set_catalog(catalog)

    def set_icons(self, store) -> None:
        self._picker.set_icons(store)

    def set_title_widget(self, widget: QWidget) -> None:
        self._picker.set_title_widget(widget)

    def set_automation(self, enabled: bool) -> None:
        """Diz se a escolha automática está ligada.

        Sem isso a tela mostraria listas caprichadas sem revelar que
        nenhuma delas seria consultada na partida.
        """
        self._automatic = enabled
        self._refresh_notice()

    # ---------- interação ----------

    def _tooltip(self, key: str) -> str:
        if key == GENERAL:
            return "Vale para toda rota que não tiver lista própria."
        return f"Usada quando o cliente te colocar em {position_name(key)}."

    def _on_tab_changed(self, index: int) -> None:
        self._current = TAB_ORDER[index]
        self._picker.set_ids(self._lists[self._current])
        self._refresh_notice()

    def _on_ids_changed(self, ids: list) -> None:
        self._lists[self._current] = list(ids)
        self._refresh_marks()
        self._refresh_notice()
        self.changed.emit(self._current, list(ids))

    def _refresh_marks(self) -> None:
        for index, key in enumerate(TAB_ORDER):
            label = TAB_LABELS[key]
            if key != GENERAL and self._lists[key]:
                label += FILLED_MARK
            self._tabs.setTabText(index, label)

    def _refresh_notice(self) -> None:
        """Diz, na aba aberta, se a lista dali vai ser usada de verdade.

        Sem isto a geral parecia mandar em tudo: dava para reordenar,
        salvar, entrar na partida e ver outro campeão ser escolhido,
        porque a rota sorteada tinha lista própria e ela é que valia.
        """
        text, alert = pick_notice(self._current, self._lists, self._automatic)
        self._picker.set_notice(text, alert)

    def notice(self) -> str:
        return self._picker.notice()

    # ---------- leitura ----------

    def general(self) -> list[int]:
        return list(self._lists[GENERAL])

    def by_position(self) -> dict[str, list[int]]:
        """Só as rotas com lista de verdade, no formato da config."""
        return {
            position: list(ids)
            for position, ids in self._lists.items()
            if position and ids
        }
