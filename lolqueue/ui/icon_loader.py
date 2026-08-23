from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QThread, Signal

from ..core.icons import AssetStore, IconStore
from ..core.items import ItemCatalog
from ..core.perks import PerkCatalog
from ..core.spells import SpellCatalog
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class IconLoader(QThread):
    """Baixa os retratos dos campeões numa thread própria.

    Não pode rodar na thread do watcher: parar o polling por vários
    segundos para baixar ~170 imagens custaria o aceite automático da
    partida. Usa uma conexão própria com o cliente do LoL pelo mesmo
    motivo — nada é compartilhado entre as duas threads.

    Na mesma viagem traz o catálogo de runas e os ícones dele: é a mesma
    natureza de trabalho (dados estáticos do cliente, lentos, que a tela
    só precisa mais tarde) e abrir uma segunda thread para ~90 imagens
    pequenas não pagaria o custo.
    """

    done = Signal()

    #: O catálogo de runas pronto, já com os ícones no disco. Vai como
    #: `object` porque é uma classe nossa, não um tipo do Qt.
    perks_ready = Signal(object)

    #: Os catálogos de item e feitiço, prontos e com os ícones no disco —
    #: a mesma natureza de trabalho das runas, para desenhar a grade do
    #: placar completo do histórico.
    catalogs_ready = Signal(object, object)

    def __init__(
        self,
        champion_ids: Iterable[int],
        store: IconStore,
        assets: AssetStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ids = list(champion_ids)
        self._store = store
        self._assets = assets
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        credentials = discover()
        if credentials is None:
            return
        client = LcuClient(credentials, timeout=5.0)
        self._store.fetch_missing(client, self._ids, lambda: self._running)
        self._load_perks(client)
        self._load_catalogs(client)
        if self._running:
            self.done.emit()

    def _load_perks(self, client) -> None:
        """Catálogo de runas e os ícones dele, se houver onde guardar.

        O aviso sai só depois das imagens: a grade avisada antes delas
        apareceria uma vez sem ícone nenhum e teria de ser redesenhada.
        Um catálogo que não veio simplesmente não avisa — a tela segue
        sem a grade, com os botões de elo funcionando.
        """
        if self._assets is None or not self._running:
            return
        catalog = PerkCatalog(client)
        catalog.load()
        if not catalog.loaded:
            return
        self._assets.fetch_missing(client, catalog.icons(), lambda: self._running)
        if self._running:
            self.perks_ready.emit(catalog)

    def _load_catalogs(self, client) -> None:
        """Catálogo de itens e de feitiços, para a grade do placar completo.

        Mesma regra tolerante dos perks: sem lugar para guardar ícone ou
        sem resposta do cliente, a tela segue sem a grade — nunca uma
        exceção suba até quem chamou.
        """
        if self._assets is None or not self._running:
            return
        items = ItemCatalog(client)
        items.load()
        spells = SpellCatalog(client)
        spells.load()
        if not items.loaded and not spells.loaded:
            return
        self._assets.fetch_missing(client, items.icons(), lambda: self._running)
        self._assets.fetch_missing(client, spells.icons(), lambda: self._running)
        if self._running:
            self.catalogs_ready.emit(items, spells)
