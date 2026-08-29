"""Ligação entre os widgets e os campos da config.

Existe porque o mesmo campo aparece em mais de um lugar da janela — o
interruptor da escolha automática mora tanto na página de Automação
quanto ao lado da lista que ele comanda. As cópias precisam concordar
sem que uma dispare a outra, e as páginas não deveriam ter que saber
umas das outras para isso.

E porque a config pode trocar por baixo da tela: ao entrar em outra
conta, o perfil dela é despejado na config em uso, e os widgets ficam
mostrando os ajustes do dono anterior até alguém clicar em algo.
`reload` é o caminho de volta — redesenha tudo o que está amarrado sem
gravar nada e sem disparar os sinais de mudança.
"""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox

from ..config import Config


class ConfigBinder(QObject):
    """Cria widgets amarrados à config e mantém as cópias em acordo."""

    #: Nome do campo que acabou de mudar.
    changed = Signal(str)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._boxes: dict[str, list[QCheckBox]] = {}
        self._combos: dict[str, list[QComboBox]] = {}
        self._reloaders: list[Callable[[], None]] = []

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

    def combo(
        self,
        attribute: str,
        options: Iterable[tuple[str, object]],
        object_name: str | None = None,
    ) -> QComboBox:
        """Uma lista suspensa amarrada a um campo da config.

        Cada opção é um par (rótulo, valor). Valor guardado que não está
        na lista deixa a caixa no primeiro item sem gravar nada: mexer na
        config só porque a tela abriu seria decidir pelo usuário.
        """
        box = QComboBox()
        if object_name:
            box.setObjectName(object_name)
        for label, value in options:
            box.addItem(label, value)
        self._show(box, getattr(self._config, attribute, None))
        box.currentIndexChanged.connect(
            lambda index, b=box, a=attribute: self.set(a, b.itemData(index))
        )
        self._combos.setdefault(attribute, []).append(box)
        return box

    def on_reload(self, restore: Callable[[], None]) -> None:
        """Registra um widget que se redesenha sozinho em `reload`.

        Para o que não passa por `checkbox` nem por `combo` — listas de
        campeões, sliders — e que mesmo assim mostra config.
        """
        self._reloaders.append(restore)

    def reload(self) -> None:
        """Redesenha tudo a partir da config, sem gravar e sem eco.

        Chamado quando a config trocou por fora — troca de conta. Os
        sinais ficam bloqueados de propósito: um `toggled` aqui gravaria
        de volta o que acabou de ser carregado, e `changed` faria o resto
        do app achar que o usuário mexeu em algo.
        """
        for attribute, boxes in self._boxes.items():
            value = bool(getattr(self._config, attribute, False))
            for box in boxes:
                if box.isChecked() == value:
                    continue
                box.blockSignals(True)
                box.setChecked(value)
                box.blockSignals(False)
        for attribute, combos in self._combos.items():
            value = getattr(self._config, attribute, None)
            for box in combos:
                self._show(box, value)
        for restore in self._reloaders:
            restore()

    @staticmethod
    def _show(box: QComboBox, value) -> None:
        index = box.findData(value)
        if index < 0 or index == box.currentIndex():
            return
        box.blockSignals(True)
        box.setCurrentIndex(index)
        box.blockSignals(False)

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
        for box in self._combos.get(attribute, []):
            self._show(box, value)
