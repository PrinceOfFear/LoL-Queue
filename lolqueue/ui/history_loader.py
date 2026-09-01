"""Busca perfil e histórico de partidas fora da thread da tela.

Ao contrário do `MatchupLoader`, que já recebe os dois lados prontos,
este loader primeiro precisa descobrir quem está jogando: abre a
própria conexão com o cliente do LoL, lê a identidade e só então
consulta o OP.GG. Uma consulta por vez — entrar e sair da página várias
vezes não deve empilhar threads pedindo a mesma coisa; quem garante
isso é a janela, que só cria um loader novo se o anterior já terminou.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.identity import current_identity
from ..core.summoner_history import SummonerHistorySource, with_local_rank_entries
from ..lcu import endpoints
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class HistoryLoader(QThread):
    #: `(Profile | None, tuple[MatchSummary, ...])`. `object` porque
    #: são classes nossas e o perfil pode vir `None`.
    ready = Signal(object, object)

    def __init__(
        self, source: SummonerHistorySource, lp_history=None, parent=None
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._lp_history = lp_history

    def run(self) -> None:
        profile = None
        matches: tuple = ()
        try:
            credentials = discover()
            if credentials is not None:
                client = LcuClient(credentials)
                identity = current_identity(client)
                if identity is not None:
                    profile = self._source.fetch_profile(
                        identity.game_name, identity.tag_line, identity.region
                    )
                    if profile is not None:
                        try:
                            profile = with_local_rank_entries(
                                profile, client.get(endpoints.CURRENT_RANKED_STATS)
                            )
                        except Exception:
                            # Se o endpoint mudou no patch, o perfil público
                            # continua sendo uma alternativa de leitura.
                            pass
                    matches = self._source.fetch_matches(
                        identity.game_name, identity.tag_line, identity.region
                    )
                    if self._lp_history is not None and matches:
                        matches = self._lp_history.enrich_matches(client, matches)
        except Exception:
            # Cliente fechado no meio da consulta, DNS falhando, o que
            # for: quem chama só precisa saber que não há dado agora.
            profile, matches = None, ()
        self.ready.emit(profile, matches)
