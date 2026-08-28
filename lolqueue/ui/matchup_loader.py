from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.matchup import MatchupSource


class MatchupLoader(QThread):
    """Busca um guia de confronto fora da thread da tela.

    A resposta passa de 50 KB e leva alguns segundos: pedida na thread
    da GUI, congelaria a janela inteira enquanto o servidor pensa. E não
    pode ir para a thread do watcher, que é a que aceita partida — o
    mesmo motivo pelo qual os retratos têm a sua.

    Uma busca por vez. Trocar de adversário no meio de uma consulta
    apenas larga a anterior: ela é daemon, some sozinha, e o sinal dela
    é descartado por quem recebe, que confere se ainda é o adversário
    pedido.
    """

    #: O guia pronto, ou `None` quando a consulta não deu em nada.
    #: `object` porque é classe nossa e porque pode vir `None`.
    ready = Signal(object, object)

    def __init__(
        self,
        source: MatchupSource,
        mine: str,
        opponent: str,
        position: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._mine = mine
        self._opponent = opponent
        self._position = position

    def run(self) -> None:
        try:
            found = self._source.fetch(self._mine, self._opponent, self._position)
        except Exception:
            # A fonte já engole o que sabe engolir; isto é a rede de
            # segurança para o que ela não previu. Uma exceção solta
            # aqui derrubaria a thread sem ninguém para contar.
            found = None
        self.ready.emit(self._opponent, found)
