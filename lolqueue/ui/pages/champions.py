from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...config import POSITIONS
from ..advice import ban_notice
from ..binding import ConfigBinder
from ..widgets.champion_picker import ChampionPicker
from ..widgets.position_picker import PositionPicker


CHAMPIONS_PAGE_STYLES = """
#championsPage { background: transparent; }
#championGuide {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(18, 58, 80, 172), stop:.55 rgba(12, 37, 63, 196),
        stop:1 rgba(7, 24, 46, 206));
    border: 1px solid rgba(107, 172, 198, 104);
    border-radius: 12px;
}
#championGuideEyebrow {
    color: #79E4DA;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.55px;
}
#championGuideText {
    color: #C8D8E2;
    font-size: 11px;
    font-weight: 600;
}
#championGuideRule {
    background: rgba(200, 170, 110, 24);
    border: 1px solid rgba(200, 170, 110, 96);
    border-radius: 8px;
    color: #F0D99E;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 7px 10px;
}
#pickChampionCard, #banChampionCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(13, 40, 67, 232), stop:.72 rgba(7, 26, 49, 238),
        stop:1 rgba(5, 19, 38, 242));
    border: 1px solid rgba(121, 164, 197, 104);
    border-radius: 15px;
}
#pickChampionCard { border-top-color: rgba(76, 214, 202, 164); }
#banChampionCard { border-top-color: rgba(220, 177, 98, 156); }
"""


class ChampionsPage(QWidget):
    """As duas listas de prioridade, lado a lado.

    Cada uma carrega o próprio interruptor de automação e o próprio
    aviso: uma lista pode estar impecável e mesmo assim não valer nada,
    e isso só aparecia na partida, tarde demais.
    """

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("championsPage")
        self.setStyleSheet(CHAMPIONS_PAGE_STYLES)
        self._binder = binder
        config = binder.config

        outer = QVBoxLayout(self)
        # A página continua arejada, mas não rouba largura das duas colunas
        # quando a janela está no tamanho mais comum do app.
        outer.setContentsMargins(14, 23, 14, 26)
        outer.setSpacing(13)
        title = QLabel("CAMPEÕES")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        subtitle = QLabel("Organize suas prioridades de escolha e banimento por rota.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        guide = QFrame()
        guide.setObjectName("championGuide")
        guide_layout = QHBoxLayout(guide)
        guide_layout.setContentsMargins(14, 10, 14, 10)
        guide_layout.setSpacing(12)
        guide_text = QVBoxLayout()
        guide_text.setContentsMargins(0, 0, 0, 0)
        guide_text.setSpacing(2)
        eyebrow = QLabel("PRIORIDADE SEM DÚVIDA")
        eyebrow.setObjectName("championGuideEyebrow")
        guide_text.addWidget(eyebrow)
        instruction = QLabel(
            "Escolha a rota, clique nos retratos e use Subir/Descer para definir a ordem."
        )
        instruction.setObjectName("championGuideText")
        instruction.setWordWrap(True)
        instruction.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        guide_text.addWidget(instruction)
        guide_layout.addLayout(guide_text, 1)
        rule = QLabel("1º DISPONÍVEL É ESCOLHIDO")
        rule.setObjectName("championGuideRule")
        guide_layout.addWidget(rule)
        outer.addWidget(guide)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

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
        pick_card.setObjectName("pickChampionCard")
        pick_layout = QVBoxLayout(pick_card)
        pick_layout.setContentsMargins(17, 17, 17, 18)
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
        ban_card.setObjectName("banChampionCard")
        ban_layout = QVBoxLayout(ban_card)
        ban_layout.setContentsMargins(17, 17, 17, 18)
        ban_layout.addWidget(self.ban_picker)
        layout.addWidget(ban_card, 1)
        outer.addLayout(layout, 1)

        binder.changed.connect(self._on_config_changed)
        binder.on_reload(self._restore_lists)
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

    def _restore_lists(self) -> None:
        """Redesenha as listas quando a config trocou por fora.

        É o caso da troca de conta: o perfil da conta que entrou já
        está na config, e sem isto as duas grades continuariam
        mostrando os campeões do dono anterior — e um arrasto aqui
        gravaria a lista errada por cima da certa.

        A grade de banimento tem o sinal calado no caminho: `set_ids`
        avisa que mudou, e esse aviso voltaria para gravar o que
        acabou de ser carregado. A de escolha já tem caminho mudo
        próprio.
        """
        config = self._binder.config
        by_position = config.pick_priority_by_position
        self.pick_picker.set_list("", config.pick_priority)
        for position in POSITIONS:
            self.pick_picker.set_list(position, by_position.get(position, []))
        self.ban_picker.blockSignals(True)
        self.ban_picker.set_ids(config.ban_priority)
        self.ban_picker.blockSignals(False)
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
