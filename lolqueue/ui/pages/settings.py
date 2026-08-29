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

        for label, attribute in (
            ("Banir campeão automaticamente", "auto_ban"),
            ("Aplicar os feitiços recomendados", "auto_spells"),
            ("Aplicar as runas recomendadas", "auto_runes"),
        ):
            automation_layout.addWidget(binder.checkbox(label, attribute))

        # Indentada porque depende da linha acima: sem as runas
        # automáticas ligadas, esta não tem efeito nenhum.
        options_row = QHBoxLayout()
        options_row.setContentsMargins(22, 0, 0, 0)
        options_row.addWidget(
            binder.checkbox(
                "Oferecer até 3 opções de runa, uma por elo, para escolher "
                "na Central",
                "auto_runes_options",
            )
        )
        options_row.addStretch(1)
        automation_layout.addLayout(options_row)

        automation_layout.addWidget(
            binder.checkbox("Montar o arsenal na loja", "auto_items")
        )
        automation_layout.addWidget(
            binder.checkbox(
                "Silenciar chat e emotes durante a seleção",
                "mute_before_game",
            )
        )
        mute_note = QLabel(
            "Desliga, nas opções do próprio jogo, o chat dos aliados, o chat "
            "de todos e os emotes dos inimigos — antes de a partida abrir, "
            "que é a única hora em que isso ainda dá para fazer. O jogo não "
            "expõe uma opção para os emotes dos aliados; essa fica de fora. "
            "Tudo volta ao que estava quando a partida termina, ou quando "
            "você desliga o motor."
        )
        mute_note.setObjectName("hint")
        mute_note.setWordWrap(True)
        automation_layout.addWidget(mute_note)

        tier_row = QHBoxLayout()
        tier_row.addWidget(QLabel("Elo das builds do OP.GG"))
        self._tier = binder.combo(
            "opgg_tier",
            [(label, tier) for tier, label in OPGG_TIERS.items()],
            "tierSelector",
        )
        tier_row.addWidget(self._tier)
        tier_row.addStretch(1)
        automation_layout.addLayout(tier_row)

        # Estas três não têm lista para configurar, e sem uma linha de
        # explicação "recomendados" não diz por quem — nem que a
        # resposta vem de fora do cliente.
        note = QLabel(
            "Feitiços, runas e itens saem do que mais venceu no OP.GG, no "
            "elo escolhido acima, para o campeão e a rota da partida; se o "
            "OP.GG não responder, valem os do próprio cliente do LoL. O app "
            "mantém uma página de runas e um conjunto de itens, ambos "
            "chamados “LoL Queue”, e não mexe nos seus. As opções de runa "
            "comparam Diamante+, Mestre e Desafiante: a do elo acima "
            "continua entrando sozinha, e as outras ficam na Central para "
            "você trocar com um clique durante a seleção."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        automation_layout.addWidget(note)

        flash_row = QHBoxLayout()
        flash_row.addWidget(QLabel("Tecla do Flash"))
        self._flash = binder.combo(
            "flash_key",
            [(label, key) for key, label in FLASH_KEYS.items()],
            "flashSelector",
        )
        flash_row.addWidget(self._flash)
        flash_row.addStretch(1)
        automation_layout.addLayout(flash_row)

        flash_note = QLabel(
            "Vale quando os feitiços recomendados entram. Em “como já "
            "estiver”, o app mantém o Flash do lado em que a conta já o "
            "tinha. Fixar o D ou o F serve para jogar em conta emprestada: "
            "a recomendação entra igual, mas o Flash vai para a tecla que "
            "você usa, e não para a do dono da conta."
        )
        flash_note.setObjectName("hint")
        flash_note.setWordWrap(True)
        automation_layout.addWidget(flash_note)

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
        automation_layout.addLayout(jungle_row)

        jungle_note = QLabel(
            "Durante a partida, o app procura o retrato do jungler inimigo "
            "no minimapa e diz em voz alta onde ele apareceu — quem está "
            "olhando a própria rota não está olhando o canto da tela. As "
            "frases são preparadas assim que a partida abre e ficam "
            "guardadas para as próximas; se a internet estiver fora no "
            "momento do preparo, o aviso fica mudo em vez de atrasar."
        )
        jungle_note.setObjectName("hint")
        jungle_note.setWordWrap(True)
        automation_layout.addWidget(jungle_note)

        automation_layout.addWidget(
            binder.checkbox(
                "Guardar no registro o porquê de cada aviso",
                "jungle_debug",
            )
        )
        debug_note = QLabel(
            "Só para investigar aviso errado. Ao lado de cada frase falada "
            "fica uma linha com a coordenada onde o retrato foi achado, a "
            "nitidez do casamento e o nome do lugar — é o que separa "
            "“achou onde não estava” de “achou certo e "
            "chamou o lugar errado”. Vale a partir da próxima partida."
        )
        debug_note.setObjectName("hint")
        debug_note.setWordWrap(True)
        automation_layout.addWidget(debug_note)

        layout.addWidget(automation)

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

        layout.addStretch(1)

        binder.on_reload(self._restore_numbers)

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
