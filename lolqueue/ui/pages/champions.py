from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..advice import ban_notice
from ..binding import ConfigBinder
from ..widgets.champion_picker import ChampionPicker
from ..widgets.position_picker import PositionPicker


class ChampionsPage(QWidget):
    """As duas listas de prioridade, lado a lado.

    Cada uma carrega o próprio interruptor de automação e o próprio
    aviso: uma lista pode estar impecável e mesmo assim não valer nada,
    e isso só aparecia na partida, tarde demais.
    """

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder
        config = binder.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 24, 36, 26)
        outer.setSpacing(16)
        title = QLabel("CAMPEÕES")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        subtitle = QLabel("Organize suas prioridades de escolha e banimento por rota.")
        subtitle.setObjectName("pageSubtitle")
        outer.addWidget(subtitle)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.pick_picker = PositionPicker(
            "PRIORIDADE DE ESCOLHA",
            config.pick_priority,
            config.pick_priority_by_position,
        )
        self.pick_picker.changed.connect(self._on_pick_changed)
        self.pick_picker.set_title_widget(
            binder.checkbox("automática", "auto_pick", object_name="autoSwitch")
        )
        pick_card = QFrame()
        pick_card.setObjectName("championCard")
        pick_layout = QVBoxLayout(pick_card)
        pick_layout.setContentsMargins(18, 16, 18, 18)
        pick_layout.addWidget(self.pick_picker)
        layout.addWidget(pick_card, 1)

        self.ban_picker = ChampionPicker("PRIORIDADE DE BANIMENTO")
        self.ban_picker.set_ids(config.ban_priority)
        self.ban_picker.changed.connect(
            lambda ids: binder.set("ban_priority", ids)
        )
        self.ban_picker.set_title_widget(
            binder.checkbox("automático", "auto_ban", object_name="autoSwitch")
        )
        ban_card = QFrame()
        ban_card.setObjectName("championCard")
        ban_layout = QVBoxLayout(ban_card)
        ban_layout.setContentsMargins(18, 16, 18, 18)
        ban_layout.addWidget(self.ban_picker)
        layout.addWidget(ban_card, 1)
        outer.addLayout(layout, 1)

        binder.changed.connect(self._on_config_changed)
        self.refresh_advice()

    # ---------- repasse ----------

    def set_icons(self, store) -> None:
        for picker in (self.pick_picker, self.ban_picker):
            picker.set_icons(store)

    def set_pick_list(self, position: str, ids) -> None:
        """Recebe a ordem que foi reordenada na Central de Fila.

        Sem este repasse a página continuaria mostrando a ordem antiga
        até o app reabrir — e um arrasto aqui depois disso desfaria, sem
        querer, o que tinha sido decidido lá.
        """
        self.pick_picker.set_list(position, ids)

    def set_catalog(self, catalog) -> None:
        for picker in (self.pick_picker, self.ban_picker):
            picker.set_catalog(catalog)

    # ---------- avisos ----------

    def _on_config_changed(self, attribute: str) -> None:
        if attribute in ("auto_pick", "auto_ban", "ban_priority"):
            self.refresh_advice()

    def refresh_advice(self) -> None:
        config = self._binder.config
        self.pick_picker.set_automation(config.auto_pick)
        self.ban_picker.set_notice(
            *ban_notice(config.ban_priority, config.auto_ban)
        )

    # ---------- escrita na config ----------

    def _on_pick_changed(self, position: str, ids: list) -> None:
        """A aba aberta diz qual lista mudou; a vazia é a geral."""
        if not position:
            self._binder.set("pick_priority", ids)
            return
        by_position = dict(self._binder.config.pick_priority_by_position)
        if ids:
            by_position[position] = ids
        else:
            by_position.pop(position, None)
        self._binder.set("pick_priority_by_position", by_position)
