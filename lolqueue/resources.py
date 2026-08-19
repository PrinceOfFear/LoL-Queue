"""Caminho dos arquivos que acompanham o código.

Rodando do fonte, os assets ficam ao lado do pacote. Dentro do `.exe`
não existe pasta: o PyInstaller descompacta tudo num diretório
temporário e diz qual é em `sys._MEIPASS`. Montar o caminho a partir
de `__file__` funcionaria só na primeira situação.
"""

from __future__ import annotations

import sys
from pathlib import Path

ASSETS = "assets"
ICON = "icon.ico"


def assets_dir() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "lolqueue" / ASSETS
    return Path(__file__).resolve().parent / ASSETS


def icon_path() -> Path:
    return assets_dir() / ICON
