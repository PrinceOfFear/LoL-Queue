"""Tipografia empacotada da interface.

O modo ``offscreen`` do Qt no Windows não enxerga as fontes do sistema.
Sem registrar uma fonte do próprio app, as prévias viram quadrados e um
build levado para outra máquina pode mudar de aparência.  Spiegel e
Beaufort são as mesmas famílias usadas pelo cliente do League; elas
viajam dentro de ``lolqueue/assets`` e por isso funcionam no fonte e nos
executáveis empacotados.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ..resources import asset_path


FONT_FILES = (
    "fonts/spiegel-regular.otf",
    "fonts/spiegel-semibold.otf",
    "fonts/spiegel-bold.otf",
    "fonts/beaufort-medium.otf",
    "fonts/beaufort-bold.otf",
    "fonts/beaufort-heavy.otf",
)


@lru_cache(maxsize=1)
def install_application_fonts() -> tuple[str, ...]:
    """Registra as fontes do app e devolve as famílias que carregaram.

    Arquivo ausente não impede a janela de abrir: o Qt continua com sua
    fonte de contingência.  Isso é importante para que um pacote antigo
    ainda consiga mostrar uma mensagem em vez de morrer durante o tema.
    """

    families: list[str] = []
    for relative in FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(str(asset_path(relative)))
        if font_id < 0:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)

    app = QApplication.instance()
    if app is not None and "Spiegel" in families:
        app.setFont(QFont("Spiegel", 10))
    return tuple(families)
