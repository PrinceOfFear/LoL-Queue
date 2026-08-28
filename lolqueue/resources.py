"""Caminho dos arquivos que acompanham o código.

Rodando do fonte, os assets ficam ao lado do pacote. Empacotado, não
existe pasta de fonte: cada empacotador expõe o diretório extraído de
um jeito diferente — PyInstaller em `sys._MEIPASS`, Nuitka em
`__main__.__compiled__.containing_dir`. Montar o caminho a partir de
`__file__` funcionaria só rodando do fonte.

`__compiled__.containing_dir` é o jeito oficial do Nuitka de indicar
isso, não `sys.argv[0]`: em modo onefile o processo real é relançado
pelo binário que o usuário abriu, mas continua com o argv[0] original
(o caminho do binário, não da pasta temporária pra onde os dados foram
extraídos) — usar `sys.argv[0]` aponta pro lugar errado e faz os
assets "sumirem" silenciosamente (ícone genérico, sem fundo).

Só que nenhum desses palpites vale sozinho: no build standalone o
ícone da barra de tarefas sumiu justamente porque o caminho anunciado
não era onde os dados estavam. Por isso aqui se pergunta ao disco em
vez de confiar no primeiro palpite — os candidatos são testados em
ordem e vale o primeiro que existe de verdade. Quando nenhum existe,
responde o primeiro mesmo assim, pra falha aparecer como arquivo
faltando e não como caminho estranho.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

ASSETS = "assets"
ICON = "icon.ico"
ICON_PNG = "icon.png"
BACKGROUND = "rift-at-dusk.png"


def _bundled_bases() -> Iterator[Path]:
    """Onde os dados empacotados podem estar, do palpite mais forte pro mais fraco."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass)

    main = sys.modules.get("__main__")
    compiled = getattr(main, "__compiled__", None)
    if compiled is None:
        return

    containing = getattr(compiled, "containing_dir", None)
    if containing:
        yield Path(containing)

    # Último recurso do binário compilado: a pasta do próprio executável.
    # No standalone é onde o Nuitka copia os dados, e é o único caminho
    # que não depende de o compilador ter anunciado o lugar certo.
    yield Path(sys.executable).resolve().parent


def _asset_dirs() -> Iterator[Path]:
    for base in _bundled_bases():
        yield base / "lolqueue" / ASSETS
    yield Path(__file__).resolve().parent / ASSETS


def assets_dir() -> Path:
    candidatos = list(_asset_dirs())
    for caminho in candidatos:
        if caminho.is_dir():
            return caminho
    return candidatos[0]


def icon_path() -> Path:
    return assets_dir() / ICON


def icon_candidates() -> list[Path]:
    """Os formatos do ícone do app, do preferido pro mais tolerante.

    O `.ico` é o formato que o Windows quer e o que vai embutido no
    executável, mas o Qt só o decodifica com o plugin `qico` carregado.
    O `.png` ele lê sozinho, sem plugin. Empacotado, é o plugin que
    pode faltar — e um ícone que não carrega deixa a janela sem nada na
    barra de tarefas, que foi exatamente o que apareceu no primeiro
    build standalone. Quem escolhe é quem consegue abrir o arquivo.
    """
    pasta = assets_dir()
    return [pasta / ICON, pasta / ICON_PNG]


def asset_path(name: str) -> Path:
    """Devolve um asset empacotado sem vazar a regra do PyInstaller pela UI."""
    return assets_dir() / name


def background_path() -> Path:
    """A arte de fundo da interface, no mesmo lugar no fonte e no .exe."""
    return asset_path(BACKGROUND)
