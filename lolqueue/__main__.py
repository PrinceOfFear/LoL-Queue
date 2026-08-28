from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import Config
from .resources import icon_candidates
from .ui.window import MainWindow

#: Identidade do app para o Windows. Sem ela, rodando pelo Python, a
#: barra de tarefas agrupa a janela sob o ícone do interpretador e
#: ignora o nosso.
APP_ID = "lolqueue.desktop"


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


def _claim_taskbar_identity() -> None:
    """Diz ao Windows que somos um app próprio, não o Python.

    Puramente cosmético e só existe no Windows — falhar aqui não pode
    impedir o app de abrir.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _app_icon() -> QIcon:
    """O primeiro ícone que o Qt realmente conseguir abrir.

    `QIcon` de um arquivo ilegível não levanta erro: devolve um ícone
    nulo, o Qt não chama `WM_SETICON`, e a janela aparece sem ícone na
    barra de tarefas sem nada explicando por quê. Perguntar `isNull()`
    é o que transforma esse silêncio em escolha do próximo formato.
    """
    for caminho in icon_candidates():
        icone = QIcon(str(caminho))
        if not icone.isNull():
            return icone
    return QIcon()


def main() -> int:
    _claim_taskbar_identity()
    app = QApplication(sys.argv)
    icone = _app_icon()
    app.setWindowIcon(icone)
    window = MainWindow(Config.load())
    # Também na janela: o ícone do QApplication é só o padrão de quem
    # não tem o seu, e no Windows quem alimenta a barra de tarefas é a
    # janela nativa.
    window.setWindowIcon(icone)
    _install_hotkeys(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
