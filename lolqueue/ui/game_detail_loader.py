"""Busca o placar completo de uma partida fora da thread da tela.

Mesmo desenho do `HistoryLoader`: abre a própria conexão com o cliente
do LoL, descobre a identidade de quem está jogando e só então consulta
o OP.GG — mas para uma partida só, a que o usuário clicou na lista.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.identity import current_identity
from ..core.summoner_history import MatchSummary, SummonerHistorySource
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class GameDetailLoader(QThread):
    #: `GameDetail | None`. `object` porque é uma classe nossa e o
    #: placar pode não vir.
    ready = Signal(object)

    def __init__(
        self, source: SummonerHistorySource, match: MatchSummary, parent=None
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._match = match

    def run(self) -> None:
        detail = None
        try:
            credentials = discover()
            if credentials is not None:
                client = LcuClient(credentials)
                identity = current_identity(client)
                if identity is not None:
                    detail = self._source.fetch_game_detail(
                        self._match.match_id,
                        self._match.played_at,
                        identity.region,
                        identity.game_name,
                        identity.tag_line,
                    )
        except Exception:
            # Cliente fechado no meio da consulta, DNS falhando, o que
            # for: quem chama só precisa saber que não há placar agora.
            detail = None
        self.ready.emit(detail)
