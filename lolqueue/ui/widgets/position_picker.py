from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTabBar, QVBoxLayout, QWidget

from ...config import POSITIONS, position_name
from .champion_picker import ChampionPicker

#: Chave da lista que vale quando a rota não tem lista própria. Vazia de
#: propósito: é o mesmo valor que o cliente manda em `assignedPosition`
#: nos modos que não distribuem rota.
GENERAL = ""

#: Rótulos curtos: a coluna não comporta "Atirador" e "Suporte" inteiros
#: em seis abas lado a lado.
TAB_LABELS: dict[str, str] = {
    GENERAL: "GERAL",
    "top": "TOPO",
    "jungle": "SELVA",
    "middle": "MEIO",
    "bottom": "ADC",
    "utility": "SUP",
}

TAB_ORDER: tuple[str, ...] = (GENERAL, *POSITIONS)

#: Marca as abas que têm lista própria, para dar de relance quais rotas
#: estão configuradas e quais caem na geral.
FILLED_MARK = " ●"


def join_names(names: list[str]) -> str:
    """Junta rótulos como se escreve à mão: A, B e C."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} e {names[-1]}"


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

        self._notice = QLabel()
        self._notice.setObjectName("listNotice")
        self._notice.setWordWrap(True)
        self._picker.add_header(self._notice)

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
        self._picker.set_catalog(catalog)

    def set_icons(self, store) -> None:
        self._picker.set_icons(store)

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
        text, alert = self._notice_for(self._current)
        self._notice.setText(text)
        self._notice.setProperty("alert", alert)
        # Propriedade dinâmica só muda a cor depois de repintar.
        self._notice.style().unpolish(self._notice)
        self._notice.style().polish(self._notice)

    def _notice_for(self, key: str) -> tuple[str, bool]:
        if key != GENERAL:
            if self._lists[key]:
                return f"Vale quando você cair de {position_name(key)}.", False
            return "Sem lista própria — esta rota usa a lista geral.", False

        overriding = [
            TAB_LABELS[position]
            for position in POSITIONS
            if self._lists[position]
        ]
        if not overriding:
            return "Vale para todas as rotas.", False
        return (
            f"{join_names(overriding)} têm lista própria e não usam esta.",
            True,
        )

    def notice(self) -> str:
        return self._notice.text()

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
