from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import OPGG_TIERS, Config, log_dir, queue_name
from ..core.champ_select import ChampSelectController
from ..core.champions import ChampionCatalog
from ..core.engine import Engine
from ..core.icons import AssetStore, IconStore
from ..core.journal import Journal
from ..core.loadout import Loadout
from ..core.matchup import MatchupSource
from ..core.opgg import OpggSource
from ..core.phases import GameflowPhase
from ..core.queues import unavailable_queues
from ..core.summoner_history import SummonerHistorySource
from ..core.watcher import PhaseWatcher
from .binding import ConfigBinder
from .game_detail_loader import GameDetailLoader
from .history_loader import HistoryLoader
from .icon_loader import IconLoader
from .matchup_loader import MatchupLoader
from .pages.analysis import AnalysisPage
from .pages.champions import ChampionsPage
from .pages.dashboard import DashboardPage
from .pages.history import HistoryPage
from .pages.queue import QueuePage
from .pages.settings import SettingsPage
from .theme import STYLESHEET
from .widgets.backdrop import Backdrop
from .widgets.sidebar import Sidebar
from .widgets.titlebar import TITLEBAR_HEIGHT, TitleBar

#: O menor tamanho em que a janela ainda mostra tudo. A largura vem do
#: painel de campeões, que é o mais largo. A altura é medida, não
#: escolhida: com a grade de runas aberta o painel pede 621 px e a barra
#: de título come outros 46. Com os 650 de antes — de quando a grade
#: ainda não existia — o cartão de registro era empurrado para fora da
#: tela em vez de simplesmente encolher.
MINIMUM_WIDTH = 1100
MINIMUM_HEIGHT = 690


class MainWindow(QWidget):
    """Moldura, navegação e o motor. Cada página cuida do seu assunto."""

    #: Ponte para ligar/desligar o motor de fora da thread da GUI.
    #: As hotkeys globais chegam pela thread do `keyboard`, que não pode
    #: tocar em widgets; a conexão em fila devolve isso à thread certa.
    engine_requested = Signal(bool)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._binder = ConfigBinder(config, self)
        self._catalog: ChampionCatalog | None = None
        # Sobrevive ao consumo de `_catalog` (zerado a cada troca de fase):
        # é dele que a prévia do próximo pick tira o nome do campeão.
        self._latest_catalog: ChampionCatalog | None = None
        self._predicted_champion: int | None = None
        # O equipamento da conexão atual. Nasce na thread do watcher e é
        # lido na da GUI, como o catálogo: o clique numa opção de runa só
        # deixa um bilhete nele, que o tick seguinte executa.
        self._loadout: Loadout | None = None
        # Filas que a Riot desligou nesta região. Descobertas na thread
        # do watcher e lidas na da GUI, igual ao catálogo.
        self._blocked_queues: set[int] | None = None
        # Vive fora do motor de propósito: assim o que já foi
        # consultado sobrevive a uma reconexão com o cliente.
        self._opgg = OpggSource()
        # Os guias de confronto, que o usuário pede clicando. Vivem fora
        # do motor pelo mesmo motivo do `_opgg`: o que já foi consultado
        # sobrevive a uma reconexão com o cliente.
        self._matchups = MatchupSource()
        self._matchup_loader: MatchupLoader | None = None
        # O perfil e as partidas consultados, pelo mesmo motivo do
        # `_opgg` e do `_matchups`: sobrevivem a uma reconexão.
        self._history_source = SummonerHistorySource()
        self._history_loader: HistoryLoader | None = None
        # O alias do campeão que está na página de análise agora.
        self._analysis_alias = ""
        self._icons = IconStore()
        # Ícones das runas e o catálogo que os nomeia. Como os retratos,
        # sobrevivem a uma reconexão: são dados estáticos do cliente.
        self._assets = AssetStore()
        self._perks = None
        # Os catálogos de item e feitiço, para a grade do histórico —
        # mesmo motivo do `_perks`: dado estático do cliente, sobrevive
        # a uma reconexão.
        self._items = None
        self._spells = None
        self._icon_loader: IconLoader | None = None
        self._game_detail_loader: GameDetailLoader | None = None
        self._phase = GameflowPhase.NONE.value
        self._phase_started = time.monotonic()
        self._drag_offset = None
        # Estado do motor guardado num atributo simples: `_make_engine` roda
        # na thread do watcher e não pode consultar widgets.
        self._enabled = False
        # O painel guarda algumas centenas de linhas e some ao fechar o
        # app. O arquivo é o que sobra para conferir, depois da partida,
        # qual lista foi usada e se o banimento entrou.
        self._journal = Journal(log_dir())

        self.setWindowTitle("LoL Queue")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # O painel de campeões é naturalmente mais largo; abrir na medida
        # certa evita a primeira impressão de uma tela apertada.
        self.resize(1280, 760)
        self.setMinimumSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)
        self.setStyleSheet(STYLESHEET)

        self._build()
        self.engine_requested.connect(
            self.set_engine_enabled, Qt.ConnectionType.QueuedConnection
        )
        self._start_watcher()

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._refresh_ring)
        self._clock.start(200)

    # ---------- construção ----------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        root = Backdrop()
        outer.addWidget(root)

        columns = QHBoxLayout(root)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.navigated.connect(self._navigate)
        columns.addWidget(self._sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(TitleBar(self.showMinimized, self.close))

        self._dashboard = DashboardPage()
        self._dashboard.toggled.connect(self.toggle_engine)
        self._dashboard.rune_option_chosen.connect(self._on_rune_option_chosen)
        self._dashboard.set_log_folder(self._journal.directory)
        self._analysis = AnalysisPage()
        self._analysis.set_icon_resolver(self._champion_icon)
        self._analysis.matchup_requested.connect(self._on_matchup_requested)
        self._history = HistoryPage()
        self._history.set_icon_resolver(self._champion_icon)
        self._history.set_name_resolver(self._champion_name)
        self._history.set_item_icon_resolver(self._item_icon)
        self._history.set_spell_icon_resolver(self._spell_icon)
        self._history.set_keystone_icon_resolver(self._match_keystone_icon)
        self._history.set_secondary_style_icon_resolver(self._match_tree_icon)
        self._history.refresh_requested.connect(self._refresh_history)
        self._history.match_selected.connect(self._open_game_detail)
        self._champions = ChampionsPage(self._binder)
        self._queue = QueuePage(self._binder)

        # A ordem tem de bater com `SECTIONS` da barra lateral: é o
        # índice do botão que escolhe a página.
        self._pages = QStackedWidget()
        for page in (
            self._dashboard,
            self._analysis,
            self._history,
            self._champions,
            self._queue,
            SettingsPage(self._binder),
        ):
            self._pages.addWidget(self._scroll_page(page))
        right.addWidget(self._pages, 1)
        columns.addLayout(right, 1)

    @staticmethod
    def _scroll_page(page: QWidget) -> QScrollArea:
        """Permite encolher a janela sem cortar controles longos.

        Em telas menores o conteúdo continua inteiro, com rolagem discreta,
        em vez de obrigar o Windows a abrir uma janela maior que a tela.
        """
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    #: Índice de "Histórico" em `SECTIONS` — mesma amarração por
    #: posição que o resto de `_build` já usa.
    _HISTORY_INDEX = 2

    def _navigate(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        if index == self._HISTORY_INDEX:
            self._refresh_history()

    # ---------- motor ----------

    def _start_watcher(self) -> None:
        self._watcher = PhaseWatcher(self._make_engine)
        self._watcher.phase_changed.connect(self._on_phase_changed)
        self._watcher.connection_changed.connect(self._on_connection_changed)
        self._watcher.message.connect(self._log_message)
        self._watcher.predicted_pick_changed.connect(self._on_predicted_pick_changed)
        self._watcher.rune_options_changed.connect(self._dashboard.set_rune_options)
        self._watcher.analysis_changed.connect(self._on_analysis_changed)
        self._watcher.start()

    def _make_engine(self, client) -> Engine:
        """Chamado na thread do watcher a cada reconexão."""
        catalog = ChampionCatalog(client)
        # Retenta: reconectar bem no instante em que o cliente do LoL
        # termina de subir cai numa corrida onde a API já responde mas os
        # dados dos campeões ainda não — sem isso o catálogo ficava vazio
        # pelo resto da conexão, e nada nunca tentava de novo.
        catalog.load_with_retries()
        self._catalog = catalog
        self._latest_catalog = catalog
        self._blocked_queues = unavailable_queues(client)
        engine = Engine(client, self._config, log=self._watcher.message.emit)
        loadout = Loadout(
            client,
            self._config,
            catalog,
            log=self._watcher.message.emit,
            source=self._opgg,
            on_rune_options=self._watcher.rune_options_changed.emit,
            on_analysis=self._watcher.analysis_changed.emit,
        )
        self._loadout = loadout
        engine.set_champ_select(
            ChampSelectController(
                client,
                self._config,
                catalog,
                log=self._watcher.message.emit,
                loadout=loadout,
                on_pick_predicted=self._watcher.predicted_pick_changed.emit,
            )
        )
        engine.set_enabled(self._enabled)
        return engine

    def toggle_engine(self) -> None:
        self.set_engine_enabled(not self._enabled)

    def set_engine_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._dashboard.set_running(enabled)
        engine = self._watcher.engine
        if engine is not None:
            engine.set_enabled(enabled)
        self._log_message("Motor ligado." if enabled else "Motor desligado.")

    def _on_phase_changed(self, phase_value: str) -> None:
        self._phase = phase_value
        self._phase_started = time.monotonic()
        if self._catalog is not None:
            catalog, self._catalog = self._catalog, None
            self._champions.set_icons(self._icons)
            self._champions.set_catalog(catalog)
            # O seletor de adversário precisa da lista inteira: o
            # oponente de rota é qualquer campeão do jogo, não só os
            # que estão nas suas prioridades.
            self._analysis.set_champions(
                [
                    (name, catalog.alias(champion_id))
                    for champion_id, name in catalog.all()
                    if catalog.alias(champion_id)
                ]
            )
            self._start_icon_loader(catalog)
        if self._blocked_queues is not None:
            blocked, self._blocked_queues = self._blocked_queues, None
            self._show_blocked_queues(blocked)
        if phase_value != GameflowPhase.CHAMP_SELECT.value:
            # A prévia só faz sentido dentro da seleção; fora dela é o
            # boneco de uma partida que já ficou para trás. As opções de
            # runa saem junto: a página só troca enquanto a seleção corre.
            self._on_predicted_pick_changed(None)
            self._dashboard.set_rune_options([], None, {})
        if phase_value == GameflowPhase.END_OF_GAME.value:
            # Pedido do usuário: o histórico não pode depender do
            # clique em "Atualizar" para saber que uma partida acabou.
            self._refresh_history()
        self._refresh_ring()

    def _show_blocked_queues(self, blocked: set[int]) -> None:
        """Marca no seletor as filas que o cliente recusa.

        Só fala quando é a fila do jogador: listar as desligadas toda vez
        que o app conecta viraria ruído, mas descobrir que a sua não abre
        só quando o motor falha é tarde demais.
        """
        self._queue.set_unavailable(blocked)
        if self._config.queue_id in blocked:
            self._log_message(
                f"{queue_name(self._config.queue_id)} está indisponível no "
                "cliente agora — escolha outra fila na aba Fila."
            )

    def _start_icon_loader(self, catalog: ChampionCatalog) -> None:
        """Busca os retratos que faltam e o catálogo de runas, uma vez.

        Não basta perguntar pelos retratos: com o cache cheio — que é o
        caso de toda abertura depois da primeira — não faltaria nenhum, e
        a carga do catálogo de runas, que vem junto, nunca aconteceria.
        A grade só apareceria para quem estivesse abrindo o app pela
        primeira vez.
        """
        ids = [champion_id for champion_id, _ in catalog.all()]
        if self._icon_loader is not None:
            return
        faltam = self._icons.missing(ids)
        tudo_carregado = (
            self._perks is not None and self._items is not None and self._spells is not None
        )
        if not faltam and tudo_carregado:
            return
        if faltam:
            self._log_message("Baixando os retratos dos campeões…")
        self._icon_loader = IconLoader(ids, self._icons, self._assets, self)
        self._icon_loader.done.connect(self._on_icons_ready)
        self._icon_loader.perks_ready.connect(self._on_perks_ready)
        self._icon_loader.catalogs_ready.connect(self._on_catalogs_ready)
        self._icon_loader.start()

    def _on_icons_ready(self) -> None:
        self._champions.set_icons(self._icons)
        self._log_message("Retratos prontos.")
        # O campeão previsto pode ter chegado antes do retrato dele —
        # sem isto a prévia ficava presa no nome até a próxima troca.
        self._render_prediction()

    def _on_perks_ready(self, catalog) -> None:
        """Entrega a tradução de runa para a tela poder desenhar a grade."""
        self._perks = catalog
        self._dashboard.set_rune_catalog(catalog, self._rune_icon)

    def _on_catalogs_ready(self, items, spells) -> None:
        """Entrega os catálogos de item e feitiço para o histórico desenhar a grade."""
        self._items = items
        self._spells = spells

    def _champion_icon(self, champion_id: int) -> str | None:
        """Onde o retrato daquele campeão ficou no disco, se ficou.

        Serve aos confrontos da análise, que vêm do OP.GG por id — e
        podem citar campeão cujo retrato ainda não baixou. Sem imagem a
        linha fica só com o nome, que já basta para ler.
        """
        return (
            str(self._icons.path_for(champion_id))
            if self._icons.has(champion_id)
            else None
        )

    def _rune_icon(self, url: str) -> str | None:
        """Onde a imagem daquela runa ficou no disco, se ficou."""
        return str(self._assets.path_for(url)) if self._assets.has(url) else None

    def _item_icon(self, item_id: int) -> str | None:
        """Onde o ícone daquele item ficou no disco, se ficou."""
        if self._items is None:
            return None
        path = self._items.icon_path(item_id)
        return self._rune_icon(path) if path else None

    def _spell_icon(self, spell_id: int) -> str | None:
        """Onde o ícone daquele feitiço ficou no disco, se ficou."""
        if self._spells is None:
            return None
        path = self._spells.icon_path(spell_id)
        return self._rune_icon(path) if path else None

    def _match_keystone_icon(self, rune_id: int) -> str | None:
        """Onde o ícone daquela runa-chave ficou no disco, se ficou."""
        if self._perks is None:
            return None
        return self._rune_icon(self._perks.perk(rune_id).icon)

    def _match_tree_icon(self, style_id: int) -> str | None:
        """Onde o ícone daquela árvore secundária ficou no disco, se ficou."""
        if self._perks is None:
            return None
        style = self._perks.style(style_id)
        return self._rune_icon(style.icon) if style is not None else None

    def _on_predicted_pick_changed(self, champion_id: int | None) -> None:
        self._predicted_champion = champion_id
        self._render_prediction()

    def _on_matchup_requested(self, opponent_alias: str, position: str) -> None:
        """Busca o guia do confronto numa thread só dele.

        Guarda a referência do loader: sem isso o Python coleta o
        `QThread` assim que este método termina, e o Qt derruba a
        thread no meio da consulta.
        """
        mine = self._analysis_alias
        if not mine:
            return
        loader = MatchupLoader(self._matchups, mine, opponent_alias, position, self)
        loader.ready.connect(self._analysis.set_matchup)
        # Sem isto cada troca de adversário deixa uma thread morta
        # pendurada na janela pelo resto da sessão: o pai a mantém viva
        # justamente para o Python não coletá-la cedo demais.
        loader.finished.connect(lambda: self._retire_matchup_loader(loader))
        self._matchup_loader = loader
        loader.start()

    def _retire_matchup_loader(self, loader) -> None:
        """Descarta o loader que terminou, se ainda for o da vez.

        Solta a referência antes de agendar a destruição: `closeEvent`
        espera nela, e esperar num objeto já destruído explodiria na
        saída do programa.
        """
        if self._matchup_loader is loader:
            self._matchup_loader = None
        loader.deleteLater()

    def _refresh_history(self) -> None:
        """Busca perfil e partidas numa thread só dela.

        Uma consulta por vez: se já há uma rodando, o pedido novo (um
        segundo clique em "Atualizar", ou abrir a página de novo bem
        rápido) não faz nada — a que já está a caminho responde para
        os dois casos.
        """
        if self._history_loader is not None:
            return
        self._history.set_loading(True)
        loader = HistoryLoader(self._history_source, self)
        loader.ready.connect(self._on_history_ready)
        loader.finished.connect(lambda: self._retire_history_loader(loader))
        self._history_loader = loader
        loader.start()

    def _retire_history_loader(self, loader) -> None:
        if self._history_loader is loader:
            self._history_loader = None
        loader.deleteLater()

    def _on_history_ready(self, profile, matches) -> None:
        self._history.set_history(profile, matches)

    def _open_game_detail(self, match) -> None:
        """Busca o placar completo de uma partida numa thread só dela.

        Uma consulta por vez, como o histórico: clicar em duas partidas
        rápido não deve empilhar duas buscas ao mesmo tempo.
        """
        if self._game_detail_loader is not None:
            return
        self._history.set_loading(True)
        loader = GameDetailLoader(self._history_source, match, self)
        loader.ready.connect(self._on_game_detail_ready)
        loader.finished.connect(lambda: self._retire_game_detail_loader(loader))
        self._game_detail_loader = loader
        loader.start()

    def _retire_game_detail_loader(self, loader) -> None:
        if self._game_detail_loader is loader:
            self._game_detail_loader = None
        loader.deleteLater()

    def _on_game_detail_ready(self, detail) -> None:
        self._history.set_game_detail(detail)

    def _champion_name(self, champion_id: int) -> str | None:
        """O nome em português do campeão, se o catálogo já carregou.

        Serve às partidas do histórico, que vêm do OP.GG com o nome em
        inglês. Sem catálogo ainda (app recém-aberto), a linha usa o
        nome que já veio na resposta.
        """
        return self._latest_catalog.name(champion_id) if self._latest_catalog else None

    def _on_analysis_changed(self, champion_id, position, build) -> None:
        """Entrega à página de análise o que o OP.GG disse do campeão.

        Não some quando a seleção acaba, ao contrário da prévia: a
        ordem de habilidade é justamente o que se consulta com o jogo
        já rodando. O que fica na tela é sempre do último campeão
        travado, que é o que está sendo jogado.
        """
        name = None
        alias = ""
        if self._latest_catalog is not None and champion_id:
            name = self._latest_catalog.name(champion_id)
            alias = self._latest_catalog.alias(champion_id)
        icon_path = (
            str(self._icons.path_for(champion_id))
            if champion_id and self._icons.has(champion_id)
            else None
        )
        # Guardado à parte porque o pedido de confronto chega depois, do
        # clique no seletor, e precisa saber quem é o nosso lado.
        self._analysis_alias = alias
        self._analysis.set_analysis(
            name,
            alias,
            icon_path,
            position,
            OPGG_TIERS.get(self._config.opgg_tier, ""),
            build,
        )

    def _on_rune_option_chosen(self, tier: str) -> None:
        """Repassa a escolha ao equipamento, sem falar com o cliente.

        Estamos na thread da GUI; quem manda requisição é a do watcher.
        O pedido fica guardado e sai no próximo tick da seleção, do
        mesmo jeito que ligar o motor daqui só acerta uma trava.
        """
        loadout = self._loadout
        if loadout is not None:
            loadout.request_rune_option(tier)

    def _render_prediction(self) -> None:
        champion_id = self._predicted_champion
        if champion_id is None or self._latest_catalog is None:
            self._dashboard.set_predicted_pick(None, None)
            return
        name = self._latest_catalog.name(champion_id)
        icon_path = (
            str(self._icons.path_for(champion_id))
            if self._icons.has(champion_id)
            else None
        )
        self._dashboard.set_predicted_pick(name, icon_path)

    def _on_connection_changed(self, connected: bool) -> None:
        self._sidebar.set_connected(connected)
        self._dashboard.ring.set_connected(connected)
        if not connected:
            # Sem cliente não há seleção nenhuma rolando — o boneco da
            # partida anterior não pode ficar preso na tela, e nem os
            # botões de runa, que não teriam a quem pedir a troca.
            #
            # `_loadout` de propósito não é apagado aqui: quem o escreve é
            # a thread do watcher, e este sinal chega atrasado. Um cliente
            # que cai e volta enquanto a GUI está ocupada faria este
            # `None` cair em cima do equipamento da conexão nova, deixando
            # os botões mortos até o app reabrir. Ficar com a referência
            # velha não custa nada: sem ninguém a rodar, o bilhete que ela
            # guardaria não é lido por ninguém.
            self._on_predicted_pick_changed(None)
            self._dashboard.set_rune_options([], None, {})

    def _refresh_ring(self) -> None:
        # Conta em toda fase, não só nas de fila. Zerado fora delas o
        # cronômetro ficava num 00:00 parado que parecia defeito.
        self._dashboard.ring.set_phase(
            self._phase, time.monotonic() - self._phase_started
        )

    def _log_message(self, message: str) -> None:
        self._dashboard.append(message)
        self._journal.write(message)

    # ---------- janela sem moldura ----------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() < TITLEBAR_HEIGHT
        ):
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._drag_offset = None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._watcher.stop()
        self._watcher.wait(3000)
        if self._icon_loader is not None:
            self._icon_loader.stop()
            self._icon_loader.wait(3000)
        if self._matchup_loader is not None:
            # Não tem como pedir para parar: está bloqueado numa
            # resposta HTTP. Esperar o timeout da consulta é curto o
            # bastante, e sair sem esperar deixaria o Qt destruir uma
            # thread ainda rodando.
            self._matchup_loader.wait(3000)
        if self._history_loader is not None:
            self._history_loader.wait(3000)
        if self._game_detail_loader is not None:
            self._game_detail_loader.wait(3000)
        event.accept()
