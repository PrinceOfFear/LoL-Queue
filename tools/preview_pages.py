"""Desenha as páginas da janela em PNG, sem abrir janela nenhuma.

Serve para conferir layout e texto sem depender do cliente do LoL nem
de captura de tela. A config é desviada para um diretório temporário —
a janela grava a cada mudança, e a do usuário não pode ser tocada.

Uso:

    py tools/preview_pages.py [pasta_de_saida]
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.window import MainWindow  # noqa: E402

PAGES = ("painel", "analise", "historico", "campeoes", "fila", "ajustes")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir())
    # `QPixmap.save` devolve False sem reclamar quando a pasta não
    # existe, e o script imprimia caminhos de arquivos que não estavam lá.
    out.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="lolqueue-preview-"))
    config_module.config_path = lambda: sandbox / "config.json"
    MainWindow._start_watcher = lambda self: None
    MainWindow._refresh_history = lambda self: None

    app = QApplication([])  # noqa: F841
    window = MainWindow(
        Config(
            auto_queue=True,
            auto_pick=True,
            auto_ban=True,
            auto_spells=True,
            auto_runes=True,
            auto_runes_options=True,
            auto_items=True,
            opgg_tier="grandmaster",
            flash_key="d",
            primary_position="middle",
            secondary_position="jungle",
        )
    )
    window.show()

    for index, name in enumerate(PAGES):
        window._navigate(index)
        app.processEvents()
        target = out / f"pagina_{index}_{name}.png"
        window.grab().save(str(target))
        print(target)

    # Ajustes é deliberadamente uma página longa. Uma segunda captura no
    # laboratório impede que os componentes mais visuais sejam validados só
    # pela metade de cima do scroll.
    window._navigate(PAGES.index("ajustes"))
    scroll = window._pages.currentWidget()
    scroll.verticalScrollBar().setValue(360)
    app.processEvents()
    target = out / "pagina_6_ajustes_build.png"
    window.grab().save(str(target))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
