from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

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

# Marca as abas que têm lista própria. O ponto fica por compatibilidade com
# quem já reconhecia esta indicação, mas o contexto abaixo agora também diz a
# quantidade e se a rota cai na Geral.
FILLED_MARK = " ●"


POSITION_PICKER_STYLES = """
#positionPicker { background: transparent; }
#routeEyebrow {
    color: #7CBFD0;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.35px;
    padding-top: 2px;
}
#positionTabs {
    background: rgba(3, 15, 30, 104);
    border: 1px solid rgba(91, 141, 181, 82);
    border-radius: 10px;
    padding: 3px;
}
#positionTabs::tab {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    color: #9CB4C6;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .6px;
    min-width: 52px;
    padding: 9px 5px;
    margin: 1px;
}
#positionTabs::tab:hover {
    background: rgba(46, 94, 127, 134);
    color: #F0F6FA;
}
#positionTabs::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(29, 99, 108, 184), stop:1 rgba(23, 57, 91, 214));
    border: 1px solid rgba(105, 229, 218, 170);
    color: #FFF0C8;
}
#routeContext {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(13, 54, 76, 164), stop:1 rgba(7, 25, 47, 178));
    border: 1px solid rgba(90, 153, 185, 102);
    border-radius: 9px;
}
#routeContext[mode="own"] {
    border-color: rgba(65, 207, 193, 154);
}
#routeContext[mode="fallback"] {
    border-color: rgba(200, 170, 110, 118);
}
#routeScopeTitle {
    color: #EEF5F7;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .7px;
}
#routeScopeDetail {
    color: #AFC6D2;
    font-size: 10px;
    font-weight: 600;
}
#routeAction {
    background: rgba(24, 67, 94, 178);
    border: 1px solid rgba(115, 172, 205, 110);
    border-radius: 7px;
    color: #DCEAF1;
    font-size: 9px;
    font-weight: 800;
    padding: 6px 8px;
}
#routeAction:hover {
    background: rgba(15, 130, 133, 126);
    border-color: rgba(104, 232, 220, 180);
    color: #F0FFFC;
}
#routeAction[clear="true"]:hover {
    background: rgba(142, 87, 34, 140);
    border-color: rgba(239, 192, 113, 190);
    color: #FFF0CE;
}
#routeAction:disabled {
    background: rgba(21, 40, 57, 94);
    border-color: rgba(91, 119, 144, 54);
    color: #708599;
}
"""


class PositionPicker(QWidget):
    """Uma lista de prioridade por rota, sobre uma biblioteca só.

    As rotas sempre aparecem em uma faixa larga. Ao trocar de rota, o cartão
    logo abaixo diz exatamente qual lista está sendo editada, quantos campeões
    ela tem e se o jogo vai usar uma prioridade própria ou a lista Geral.
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
        self.setObjectName("positionPicker")
        self.setStyleSheet(POSITION_PICKER_STYLES)
        self._lists: dict[str, list[int]] = {GENERAL: list(general)}
        for position in POSITIONS:
            self._lists[position] = list(by_position.get(position) or [])
        self._current = GENERAL
        # Começa ligada para que o aviso não acuse desligamento antes de a
        # janela dizer como a config está de fato.
        self._automatic = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._picker = ChampionPicker(title)
        layout.addWidget(self._picker)

        route_eyebrow = QLabel("ESCOLHA A ROTA QUE VOCÊ QUER EDITAR")
        route_eyebrow.setObjectName("routeEyebrow")
        self._picker.add_header(route_eyebrow)

        self._tabs = QTabBar()
        self._tabs.setObjectName("positionTabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(True)
        self._tabs.setUsesScrollButtons(False)
        self._tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self._tabs.setMinimumHeight(44)
        for key in TAB_ORDER:
            index = self._tabs.addTab(TAB_LABELS[key])
            self._tabs.setTabToolTip(index, self._tooltip(key))
        self._picker.add_header(self._tabs)

        self._route_context = QFrame()
        self._route_context.setObjectName("routeContext")
        context_layout = QHBoxLayout(self._route_context)
        context_layout.setContentsMargins(11, 8, 10, 8)
        context_layout.setSpacing(8)

        context_text = QVBoxLayout()
        context_text.setContentsMargins(0, 0, 0, 0)
        context_text.setSpacing(2)
        self._scope_title = QLabel()
        self._scope_title.setObjectName("routeScopeTitle")
        context_text.addWidget(self._scope_title)
        self._scope_detail = QLabel()
        self._scope_detail.setObjectName("routeScopeDetail")
        self._scope_detail.setWordWrap(True)
        context_text.addWidget(self._scope_detail)
        context_layout.addLayout(context_text, 1)

        self._general_button = QPushButton("Editar GERAL")
        self._general_button.setObjectName("routeAction")
        self._general_button.setToolTip("Abre a lista usada nas rotas sem prioridade própria.")
        self._general_button.clicked.connect(self._edit_general)
        context_layout.addWidget(self._general_button)

        self._fallback_button = QPushButton()
        self._fallback_button.setObjectName("routeAction")
        self._fallback_button.setProperty("clear", True)
        self._fallback_button.clicked.connect(self.clear_current_position)
        context_layout.addWidget(self._fallback_button)
        self._picker.add_header(self._route_context)

        self._picker.set_ids(self._lists[GENERAL])
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._picker.changed.connect(self._on_ids_changed)
        self._refresh_marks()
        self._refresh_scope()
        self._refresh_notice()

    # ---------- repasse para a grade ----------

    def set_catalog(self, catalog) -> None:
        """Poda todas as listas, não só a que está à vista."""
        if catalog is not None and catalog.loaded:
            for key, ids in self._lists.items():
                kept = [c for c in ids if catalog.knows(c)]
                if kept != ids:
                    self._lists[key] = kept
                    self.changed.emit(key, kept)
            self._picker.set_ids(self._lists[self._current])
            self._refresh_marks()
            self._refresh_scope()
            self._refresh_notice()
        self._picker.set_catalog(catalog)

    def set_icons(self, store) -> None:
        self._picker.set_icons(store)

    def set_title_widget(self, widget: QWidget) -> None:
        self._picker.set_title_widget(widget)

    def set_automation(self, enabled: bool) -> None:
        """Diz se a escolha automática está ligada."""
        self._automatic = enabled
        self._refresh_notice()

    def set_list(self, position: str, ids) -> None:
        """Escreve uma lista vinda de fora sem devolver o eco."""
        if position not in self._lists:
            return
        ids = [int(champion_id) for champion_id in ids]
        if self._lists[position] == ids:
            return
        self._lists[position] = ids
        if position == self._current:
            # ``set_ids`` é silencioso; ainda assim desliga a ponte enquanto
            # desenha para manter o contrato claro e evitar regressão.
            self._picker.changed.disconnect(self._on_ids_changed)
            self._picker.set_ids(ids)
            self._picker.changed.connect(self._on_ids_changed)
        self._refresh_marks()
        self._refresh_scope()
        self._refresh_notice()

    # ---------- interação ----------

    def _tooltip(self, key: str) -> str:
        if key == GENERAL:
            return "Lista Geral: usada onde não houver uma lista própria."
        count = len(self._lists.get(key, []))
        if count:
            return (
                f"{position_name(key)}: lista própria com {count} "
                f"campeão{'es' if count != 1 else ''}."
            )
        return f"{position_name(key)}: usa a lista Geral enquanto estiver vazia."

    def _on_tab_changed(self, index: int) -> None:
        self._current = TAB_ORDER[index]
        self._picker.set_ids(self._lists[self._current])
        self._refresh_scope()
        self._refresh_notice()

    def _on_ids_changed(self, ids: list) -> None:
        self._lists[self._current] = list(ids)
        self._refresh_marks()
        self._refresh_scope()
        self._refresh_notice()
        self.changed.emit(self._current, list(ids))

    def _edit_general(self) -> None:
        """Troca de volta para a lista que serve de fallback."""
        self._tabs.setCurrentIndex(TAB_ORDER.index(GENERAL))

    def clear_current_position(self) -> None:
        """Remove só a lista da rota aberta e volta seu uso para a Geral.

        A lista Geral não é tocada. Assim a ação é reversível: basta voltar à
        rota e escolher novos campeões, sem risco de apagar as outras rotas.
        """
        if self._current == GENERAL or not self._lists[self._current]:
            return
        self._lists[self._current] = []
        self._picker.set_ids([])
        self._refresh_marks()
        self._refresh_scope()
        self._refresh_notice()
        self.changed.emit(self._current, [])

    def _refresh_marks(self) -> None:
        for index, key in enumerate(TAB_ORDER):
            label = TAB_LABELS[key]
            if key != GENERAL and self._lists[key]:
                label += FILLED_MARK
            self._tabs.setTabText(index, label)
            self._tabs.setTabToolTip(index, self._tooltip(key))

    def _refresh_scope(self) -> None:
        """Explica o alcance da lista aberta sem exigir inferência das abas."""
        current_ids = self._lists[self._current]
        count = len(current_ids)
        if self._current == GENERAL:
            covered = [position for position in POSITIONS if self._lists[position]]
            self._scope_title.setText(
                f"LISTA GERAL  ·  {count} CAMPEÃO" + ("" if count == 1 else "ES")
            )
            if covered:
                labels = join_names([TAB_LABELS[position] for position in covered])
                detail = f"É usada nas outras rotas; {labels} têm prioridade própria."
                mode = "general"
            else:
                detail = "É a prioridade usada em todas as cinco rotas."
                mode = "general"
            self._general_button.setVisible(False)
            self._fallback_button.setVisible(False)
        else:
            lane = position_name(self._current).upper()
            if count:
                self._scope_title.setText(
                    f"{lane}  ·  {count} CAMPEÃO" + ("" if count == 1 else "ES")
                )
                detail = "Lista própria ativa: ela substitui a Geral quando você cair nesta rota."
                mode = "own"
                fallback_text = "↶  Usar GERAL"
                fallback_tooltip = (
                    f"Limpa somente a lista de {position_name(self._current)} e "
                    "faz a rota voltar a usar a lista Geral."
                )
                fallback_enabled = True
            else:
                general_count = len(self._lists[GENERAL])
                self._scope_title.setText(f"{lane}  ·  USANDO A GERAL")
                detail = (
                    f"Sem lista própria. Nesta rota, o jogo usará os {general_count} "
                    "campeões da lista Geral."
                )
                mode = "fallback"
                fallback_text = "✓  Usa GERAL"
                fallback_tooltip = "Esta rota já cai na lista Geral."
                fallback_enabled = False
            self._general_button.setVisible(True)
            self._fallback_button.setVisible(True)
            self._fallback_button.setText(fallback_text)
            self._fallback_button.setToolTip(fallback_tooltip)
            self._fallback_button.setEnabled(fallback_enabled)

        self._scope_detail.setText(detail)
        self._route_context.setProperty("mode", mode)
        self._route_context.style().unpolish(self._route_context)
        self._route_context.style().polish(self._route_context)

    def _refresh_notice(self) -> None:
        """Diz, na aba aberta, se a lista dali vai ser usada de verdade."""
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
