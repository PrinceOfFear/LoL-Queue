from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import Config
from .ui.window import MainWindow


def _install_hotkeys(window: MainWindow) -> None:
    """F5 e F6 globais. Falhar aqui não impede o app de funcionar.

    O callback vem da thread do `keyboard`, então emite um sinal em vez
    de mexer em widgets — Qt só aceita GUI na própria thread.
    """
    try:
        import keyboard
    except ImportError:
        return
    try:
        keyboard.add_hotkey("F5", lambda: window.engine_requested.emit(True))
        keyboard.add_hotkey("F6", lambda: window.engine_requested.emit(False))
    except Exception:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(Config.load())
    _install_hotkeys(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
