from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    ACCEPT_DELAY_CEILING,
    FLASH_KEYS,
    JUNGLE_VOICE_LABELS,
    OPGG_TIERS,
    PICK_INTENT_CEILING,
)
from ..binding import ConfigBinder
from ..widgets.accounts_card import AccountsCard
from ..widgets.loadout_studio import (
    RankPreview,
    SpellKeyPreview,
    decorate_rank_combo,
)
from ..widgets.update_card import UpdateCard


class SettingsPage(QWidget):
    """Os interruptores da automação e as faixas de atraso."""

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 28)
        layout.setSpacing(16)

        title = QLabel("AJUSTES")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Decida o quanto o LoL Queue deve agir por você.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        automation = QFrame()
        automation.setObjectName("settingsCard")
        automation_layout = QVBoxLayout(automation)
        automation_layout.setContentsMargins(24, 20, 24, 20)
        automation_layout.setSpacing(7)
        automation_title = QLabel("AUTOMAÇÃO")
        automation_title.setObjectName("sectionTitle")
        automation_layout.addWidget(automation_title)

        for label, attribute in (
            ("Aceitar partida automaticamente", "auto_accept"),
            ("Escolher campeão automaticamente", "auto_pick"),
        ):
            automation_layout.addWidget(binder.checkbox(label, attribute))

        # Indentada porque depende da linha acima: o retrato que aparece
        # no cliente é o que aquela lista vai travar, e sem a escolha
        # automática não há nada a antecipar.
        intent_row = QHBoxLayout()
        intent_row.setContentsMargins(22, 0, 0, 0)
        intent_row.addWidget(
            binder.checkbox(
                "Mostrar no cliente do LoL, antes da sua vez, o campeão que "
                "será escolhido",
                "show_pick_intent",
            )
        )
        intent_row.addStretch(1)
        automation_layout.addLayout(intent_row)

        # Também indentada: sem o retrato ligado acima, não há o que
        # atrasar.
        self._intent_delay = self._seconds_row(
            automation_layout,
            "Esperar antes de mostrar, para o time não ver o pick cedo demais",
            "pick_intent_delay",
            ceiling=PICK_INTENT_CEILING,
            indent=22,
        )

        automation_layout.addWidget(
            binder.checkbox("Banir campeão automaticamente", "auto_ban")
        )
        automation_layout.addWidget(
            binder.checkbox(
                "Silenciar chat e emotes durante a seleção",
                "mute_before_game",
            )
        )
        mute_note = QLabel(
            "Protege a seleção desligando chat e emotes inimigos. Tudo volta "
            "ao estado anterior quando a partida termina ou a automação para."
        )
        mute_note.setObjectName("hint")
        mute_note.setWordWrap(True)
        automation_layout.addWidget(mute_note)

        layout.addWidget(automation)

        # O antigo cartão único misturava decisões de fila, build e aviso
        # de voz. O laboratório dá às escolhas de equipamento uma linguagem
        # própria — com os mesmos assets que o jogador reconhece no cliente.
        loadout = QFrame()
        loadout.setObjectName("loadoutStudioCard")
        loadout_layout = QVBoxLayout(loadout)
        loadout_layout.setContentsMargins(24, 20, 24, 22)
        loadout_layout.setSpacing(12)

        loadout_heading = QHBoxLayout()
        loadout_title = QLabel("LABORATÓRIO DE BUILD")
        loadout_title.setObjectName("sectionTitle")
        loadout_heading.addWidget(loadout_title)
        loadout_heading.addStretch(1)
        source_badge = QLabel("ASSETS ORIGINAIS DO JOGO")
        source_badge.setObjectName("featureBadge")
        loadout_heading.addWidget(source_badge)
        loadout_layout.addLayout(loadout_heading)

        loadout_subtitle = QLabel(
            "Escolha a faixa competitiva e veja como os feitiços serão "
            "organizados antes de entrar na seleção."
        )
        loadout_subtitle.setObjectName("heroDetail")
        loadout_subtitle.setWordWrap(True)
        loadout_layout.addWidget(loadout_subtitle)

        automation_columns = QHBoxLayout()
        automation_columns.setSpacing(28)
        build_left = QVBoxLayout()
        build_left.setSpacing(2)
        build_left.addWidget(
            binder.checkbox("Aplicar os feitiços recomendados", "auto_spells")
        )
        build_left.addWidget(
            binder.checkbox("Aplicar as runas recomendadas", "auto_runes")
        )
        build_right = QVBoxLayout()
        build_right.setSpacing(2)
        build_right.addWidget(
            binder.checkbox("Montar o arsenal na loja", "auto_items")
        )
        build_right.addWidget(
            binder.checkbox(
                "Oferecer até 3 opções de runa por elo na Central",
                "auto_runes_options",
            )
        )
        automation_columns.addLayout(build_left, 1)
        automation_columns.addLayout(build_right, 1)
        loadout_layout.addLayout(automation_columns)

        studio = QHBoxLayout()
        studio.setSpacing(12)

        rank_panel = QFrame()
        rank_panel.setObjectName("studioPanel")
        rank_layout = QVBoxLayout(rank_panel)
        rank_layout.setContentsMargins(16, 14, 16, 16)
        rank_layout.setSpacing(9)
        rank_label = QLabel("ELO DA BUILD DO OP.GG")
        rank_label.setObjectName("predictionEyebrow")
        rank_layout.addWidget(rank_label)

        tier_row = QHBoxLayout()
        self._tier = binder.combo(
            "opgg_tier",
            [(label, tier) for tier, label in OPGG_TIERS.items()],
            "tierSelector",
        )
        decorate_rank_combo(self._tier)
        tier_row.addWidget(self._tier, 1)
        rank_layout.addLayout(tier_row)
        self._rank_preview = RankPreview()
        rank_layout.addWidget(self._rank_preview)
        studio.addWidget(rank_panel, 1)

        flash_panel = QFrame()
        flash_panel.setObjectName("studioPanel")
        flash_layout = QVBoxLayout(flash_panel)
        flash_layout.setContentsMargins(16, 14, 16, 16)
        flash_layout.setSpacing(9)
        flash_label = QLabel("SIMULAÇÃO DOS FEITIÇOS")
        flash_label.setObjectName("predictionEyebrow")
        flash_layout.addWidget(flash_label)

        flash_row = QHBoxLayout()
        self._flash = binder.combo(
            "flash_key",
            [(label, key) for key, label in FLASH_KEYS.items()],
            "flashSelector",
        )
        flash_row.addWidget(self._flash, 1)
        flash_layout.addLayout(flash_row)
        self._spell_preview = SpellKeyPreview()
        flash_layout.addWidget(self._spell_preview)
        studio.addWidget(flash_panel, 1)
        loadout_layout.addLayout(studio)

        note = QLabel(
            "A build usa os dados de vitória do OP.GG para o campeão, rota e "
            "elo escolhidos. Se a fonte não responder, runas e feitiços usam "
            "a recomendação do próprio cliente; suas páginas pessoais não são "
            "alteradas. A Barreira acima serve apenas para visualizar os slots."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        loadout_layout.addWidget(note)
        layout.addWidget(loadout)

        assistance = QFrame()
        assistance.setObjectName("settingsCard")
        assistance_layout = QVBoxLayout(assistance)
        assistance_layout.setContentsMargins(24, 20, 24, 20)
        assistance_layout.setSpacing(8)
        assistance_title = QLabel("ASSISTÊNCIA DURANTE A PARTIDA")
        assistance_title.setObjectName("sectionTitle")
        assistance_layout.addWidget(assistance_title)

        jungle_row = QHBoxLayout()
        jungle_row.addWidget(
            binder.checkbox(
                "Avisar o jungler inimigo por voz",
                "jungle_callouts",
            )
        )
        self._voice = binder.combo(
            "jungle_voice",
            [(label, voice) for voice, label in JUNGLE_VOICE_LABELS.items()],
            "voiceSelector",
        )
        jungle_row.addWidget(self._voice)
        jungle_row.addStretch(1)
        assistance_layout.addLayout(jungle_row)

        jungle_note = QLabel(
            "O minimapa é acompanhado durante a partida e a voz informa onde "
            "o jungler inimigo apareceu, sem tirar seus olhos da rota."
        )
        jungle_note.setObjectName("hint")
        jungle_note.setWordWrap(True)
        assistance_layout.addWidget(jungle_note)

        assistance_layout.addWidget(
            binder.checkbox(
                "Precisão máxima — só avisa com confirmação reforçada",
                "jungle_max_precision",
                "jungleMaxPrecision",
            )
        )
        precision_note = QLabel(
            "Prioriza não falar a adivinhar: confirma imagem, movimento e "
            "zona antes do aviso. Pode ignorar aparições rápidas ou sob "
            "névoa; a escolha vale na próxima partida."
        )
        precision_note.setObjectName("hint")
        precision_note.setWordWrap(True)
        assistance_layout.addWidget(precision_note)

        assistance_layout.addWidget(
            binder.checkbox(
                "Guardar no registro o porquê de cada aviso",
                "jungle_debug",
            )
        )
        debug_note = QLabel(
            "Modo técnico: registra coordenada, confiança e zona detectada "
            "para investigar um aviso incorreto."
        )
        debug_note.setObjectName("hint")
        debug_note.setWordWrap(True)
        assistance_layout.addWidget(debug_note)
        layout.addWidget(assistance)

        timing_card = QFrame()
        timing_card.setObjectName("settingsCard")
        timing_layout = QVBoxLayout(timing_card)
        timing_layout.setContentsMargins(24, 20, 24, 20)
        timing_layout.setSpacing(11)
        timing = QLabel("TEMPO DE REAÇÃO")
        timing.setObjectName("sectionTitle")
        timing_layout.addWidget(timing)

        self._lock_delay = self._delay_row(
            timing_layout, "Mostrar o campeão antes de travar",
            "lock_delay_min", "lock_delay_max", ceiling=30.0,
        )
        self._accept_delay = self._delay_row(
            timing_layout, "Esperar antes de aceitar a partida",
            "accept_delay_min", "accept_delay_max", ceiling=ACCEPT_DELAY_CEILING,
        )
        self._postgame_delay = self._delay_row(
            timing_layout, "Esperar depois da partida antes de buscar outra",
            "postgame_delay_min", "postgame_delay_max", ceiling=120.0,
        )

        timing_note = QLabel(
            "O app sorteia um tempo dentro da faixa a cada partida. Os dois "
            "primeiros te dão margem de intervir — cancelar a fila, trocar "
            "de campeão. O aceite tem teto de "
            f"{ACCEPT_DELAY_CEILING:.0f} s porque a janela do “Partida "
            "encontrada” fecha por volta dos 12. Já a espera depois da "
            "partida evita erro: o cliente do LoL recusa a fila enquanto "
            "encerra a anterior, o que leva de 5 a 10 segundos."
        )
        timing_note.setObjectName("hint")
        timing_note.setWordWrap(True)
        timing_layout.addWidget(timing_note)
        layout.addWidget(timing_card)

        self.accounts = AccountsCard()
        layout.addWidget(self.accounts)

        # A troca de arquivos e feita pela janela, em threads separadas; a
        # pagina so abriga o cartao para manter Ajustes como a casa de tudo
        # que diz respeito a manutencao do aplicativo.
        self.updates = UpdateCard()
        layout.addWidget(self.updates)

        legal = QLabel(
            "PROJETO INDEPENDENTE · LoL Queue não é endossado pela Riot Games. "
            "League of Legends e suas propriedades pertencem à Riot Games, Inc."
        )
        legal.setObjectName("legalNotice")
        legal.setWordWrap(True)
        layout.addWidget(legal)

        layout.addStretch(1)

        binder.on_reload(self._restore_numbers)
        binder.on_reload(self._restore_visuals)
        binder.changed.connect(self._refresh_visual_setting)
        self._restore_visuals()

    def _refresh_visual_setting(self, attribute: str) -> None:
        if attribute in {"opgg_tier", "flash_key"}:
            self._restore_visuals()

    def _restore_visuals(self, *_args) -> None:
        """Mantém brasão e slots em acordo inclusive após trocar de conta."""

        tier = self._binder.config.opgg_tier
        self._rank_preview.set_tier(tier, OPGG_TIERS.get(tier, tier))
        self._spell_preview.set_key(self._binder.config.flash_key)

    def _restore_numbers(self) -> None:
        """Traz os números de volta do que a config diz agora.

        As caixas de segundos não passam pelo `ConfigBinder` — elas
        gravam direto —, então a troca de conta não as alcançaria. Os
        sinais ficam bloqueados: `setValue` aqui gravaria de volta o
        que acabou de ser carregado.
        """
        config = self._binder.config
        pairs = [(self._intent_delay, "pick_intent_delay")]
        for boxes, low, high in (
            (self._lock_delay, "lock_delay_min", "lock_delay_max"),
            (self._accept_delay, "accept_delay_min", "accept_delay_max"),
            (self._postgame_delay, "postgame_delay_min", "postgame_delay_max"),
        ):
            pairs += [(boxes[0], low), (boxes[1], high)]
        for box, attribute in pairs:
            value = getattr(config, attribute)
            if box.value() == value:
                continue
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _seconds_row(
        self,
        layout: QVBoxLayout,
        label: str,
        attribute: str,
        ceiling: float,
        indent: int = 0,
    ) -> QDoubleSpinBox:
        """Uma linha de um número só de segundos, ligada a um campo.

        Irmã de `_delay_row`, para o caso em que não há faixa a sortear:
        a espera é fixa porque o que ela protege é a hora de aparecer,
        não o compasso do app.
        """
        row = QHBoxLayout()
        row.setContentsMargins(indent, 0, 0, 0)
        row.addWidget(QLabel(label))
        box = QDoubleSpinBox()
        box.setRange(0.0, ceiling)
        box.setSingleStep(0.5)
        box.setSuffix(" s")
        box.setValue(getattr(self._binder.config, attribute))
        box.valueChanged.connect(lambda value: self._binder.set(attribute, value))
        row.addWidget(box)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _delay_row(
        self,
        layout: QVBoxLayout,
        label: str,
        low_attr: str,
        high_attr: str,
        ceiling: float,
    ) -> tuple[QDoubleSpinBox, QDoubleSpinBox]:
        """Uma linha "de X a Y segundos" ligada a dois campos da config.

        Os dois se empurram: mexer no mínimo levanta o máximo junto, e
        vice-versa. Sem isso dá para deixar a faixa invertida na tela —
        a config endireita ao gravar, mas o número na tela mentiria.
        """
        row = QHBoxLayout()
        row.addWidget(QLabel(label))

        low = QDoubleSpinBox()
        high = QDoubleSpinBox()
        for box in (low, high):
            box.setRange(0.0, ceiling)
            box.setSingleStep(0.5)
            box.setSuffix(" s")
        low.setValue(getattr(self._binder.config, low_attr))
        high.setValue(getattr(self._binder.config, high_attr))

        def on_low(value: float) -> None:
            self._binder.set(low_attr, value)
            if value > high.value():
                high.setValue(value)

        def on_high(value: float) -> None:
            if value < low.value():
                value = low.value()
                high.setValue(value)
            self._binder.set(high_attr, value)

        low.valueChanged.connect(on_low)
        high.valueChanged.connect(on_high)

        row.addWidget(low)
        row.addWidget(QLabel("a"))
        row.addWidget(high)
        row.addStretch(1)
        layout.addLayout(row)
        return (low, high)
