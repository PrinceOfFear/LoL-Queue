from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..binding import ConfigBinder


class SettingsPage(QWidget):
    """Os interruptores da automação e o atraso antes de travar."""

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 28)
        layout.setSpacing(14)

        title = QLabel("AUTOMAÇÃO")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        for label, attribute in (
            ("Aceitar partida automaticamente", "auto_accept"),
            ("Escolher campeão automaticamente", "auto_pick"),
            ("Banir campeão automaticamente", "auto_ban"),
            ("Aplicar os feitiços recomendados", "auto_spells"),
            ("Aplicar as runas recomendadas", "auto_runes"),
        ):
            layout.addWidget(binder.checkbox(label, attribute))

        # Estes dois não têm lista para configurar, e sem uma linha de
        # explicação "recomendados" não diz por quem.
        note = QLabel(
            "Feitiços e runas saem da recomendação do próprio cliente do LoL "
            "para o campeão e a rota da partida. O app mantém uma única "
            "página de runas, chamada “LoL Queue”, e não mexe nas suas."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Atraso antes de travar o campeão"))
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0.0, 15.0)
        self._delay.setSingleStep(0.5)
        self._delay.setSuffix(" s")
        self._delay.setValue(binder.config.lock_delay_seconds)
        self._delay.valueChanged.connect(
            lambda value: binder.set("lock_delay_seconds", value)
        )
        delay_row.addWidget(self._delay)
        delay_row.addStretch(1)
        layout.addLayout(delay_row)

        layout.addStretch(1)
