"""Onde ficam os arquivos que não são código.

Dentro do `.exe` o pacote não é uma pasta no disco: o PyInstaller
descompacta tudo num diretório temporário e conta em `sys._MEIPASS`.
Um caminho montado a partir de `__file__` aponta para dentro do
arquivo compactado e não abre.
"""

import sys

from lolqueue import resources


def test_the_icon_travels_with_the_package():
    assert resources.icon_path().parts[-2:] == ("assets", "icon.ico")


def test_the_icon_file_is_really_there():
    """O ícone é versionado; `tools/make_icon.py` o regera."""
    assert resources.icon_path().is_file()


def test_inside_the_exe_it_reads_from_the_unpacked_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resources.icon_path() == tmp_path / "lolqueue" / "assets" / "icon.ico"


def test_outside_the_exe_it_reads_from_the_source_tree(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert resources.icon_path().is_file()
