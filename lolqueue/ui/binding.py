"""Ligação entre os widgets e os campos da config.

Existe porque o mesmo campo aparece em mais de um lugar da janela — o
interruptor da escolha automática mora tanto na página de Automação
quanto ao lado da lista que ele comanda. As cópias precisam concordar
sem que uma dispare a outra, e as páginas não deveriam ter que saber
umas das outras para isso.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox

from ..config import Config


class ConfigBinder(QObject):
    """Cria widgets amarrados à config e mantém as cópias em acordo."""

    #: Nome do campo que acabou de mudar.
    changed = Signal(str)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._boxes: dict[str, list[QCheckBox]] = {}

    @property
    def config(self) -> Config:
        return self._config

    def checkbox(
        self, label: str, attribute: str, object_name: str | None = None
    ) -> QCheckBox:
        box = QCheckBox(label)
        if object_name:
            box.setObjectName(object_name)
        box.setChecked(getattr(self._config, attribute))
        box.toggled.connect(lambda value: self.set(attribute, value))
        self._boxes.setdefault(attribute, []).append(box)
        return box

    def boxes(self, attribute: str) -> list[QCheckBox]:
        return list(self._boxes.get(attribute, []))

    def set(self, attribute: str, value) -> None:
        setattr(self._config, attribute, value)
        self._config.save()
        self._sync(attribute, value)
        self.changed.emit(attribute)

    def _sync(self, attribute: str, value) -> None:
        """Alinha as outras caixas do mesmo campo, sem reentrância.

        Marcar uma caixa daqui dispararia `toggled` de novo, e o eco
        voltaria para cá só para gravar o que já estava gravado.
        """
        for box in self._boxes.get(attribute, []):
            if box.isChecked() == value:
                continue
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
