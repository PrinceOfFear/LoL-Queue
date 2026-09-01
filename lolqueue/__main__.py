from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

from .config import Config
from .licenca import porta
from .resources import icon_candidates
from .ui.widgets.license_dialog import LicenseDialog
from .version import VERSION
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


def _license_gate() -> bool:
    """So deixa a janela principal existir depois da verificacao local."""
    result = porta.verificar()
    if result.liberado:
        return True
    dialog = LicenseDialog(VERSION)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    return porta.verificar().liberado


class _LicenseRenewal(QObject):
    """Renova bilhete fora da thread da GUI e fecha se o servidor revogar."""

    result_ready = Signal(object)

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lolqueue-license")
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(porta.INTERVALO_RENOVACAO * 1000)
        self._timer.timeout.connect(self._renew)
        self.result_ready.connect(self._finished)
        self._timer.start()

    def _renew(self) -> None:
        if self._busy:
            return
        self._busy = True
        future = self._pool.submit(porta.renovar)

        def done(completed) -> None:
            try:
                value = completed.result()
            except Exception as error:  # noqa: BLE001 - falha nao pode matar a GUI
                value = error
            self.result_ready.emit(value)

        future.add_done_callback(done)

    def _finished(self, value: object) -> None:
        self._busy = False
        if isinstance(value, Exception):
            return  # a licença guardada ainda decide até o prazo expirar
        if getattr(value, "liberado", True):
            return
        QMessageBox.critical(
            self._window,
            "Assinatura encerrada",
            "A assinatura deste computador não está mais ativa. "
            "O LoL Queue será fechado.",
        )
        self._window.close()

    def stop(self) -> None:
        self._timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    _claim_taskbar_identity()
    app = QApplication(sys.argv)
    icone = _app_icon()
    app.setWindowIcon(icone)
    if not _license_gate():
        return 0
    window = MainWindow(Config.load())
    # Também na janela: o ícone do QApplication é só o padrão de quem
    # não tem o seu, e no Windows quem alimenta a barra de tarefas é a
    # janela nativa.
    window.setWindowIcon(icone)
    renewal = _LicenseRenewal(window)
    window._license_renewal = renewal
    window.destroyed.connect(lambda: renewal.stop())
    _install_hotkeys(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
