from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..atualizacao import (
    GithubReleaseClient,
    UpdateError,
    UpdateNotAvailable,
    current_installation,
    launch_prepared_update,
)
from ..config import OPGG_TIERS, Config, log_dir, position_name, queue_name
from ..core.accounts import (
    ARRIVED_FIRST,
    ARRIVED_INHERITED,
    Accounts,
)
from ..core.antitoxic import MuteGuard
from ..core.champ_select import ChampSelectController
from ..core.champions import ChampionCatalog
from ..core.engine import Engine
from ..core.gamesettings import GameSettingsSync
from ..core.icons import AssetStore, IconStore
from ..core.journal import Journal
from ..core.loadout import Loadout
from ..core.lp_history import LpChangeTracker, LpHistory, format_lp_delta
from ..core.matchup import MatchupSource
from ..core.opgg import OpggSource
from ..core.phases import GameflowPhase
from ..core.queues import unavailable_queues
from ..core.summoner_history import SummonerHistorySource
from ..core.watcher import PhaseWatcher
from .binding import ConfigBinder
from .fonts import install_application_fonts
from .game_detail_loader import GameDetailLoader
from .history_loader import HistoryLoader
from .icon_loader import IconLoader
from .lp_import_loader import LpImportLoader
from .matchup_loader import MatchupLoader
from .security_loader import SecurityCheckLoader
from .update_loader import UpdateCheckLoader, UpdateDownloadLoader
from .pages.analysis import AnalysisPage
from .pages.champions import ChampionsPage
from .pages.dashboard import DashboardPage
from .pages.history import HistoryPage
from .pages.queue import QueuePage
from .pages.settings import SettingsPage
from .theme import STYLESHEET
from .widgets.backdrop import Backdrop
from .widgets.manual_lp_import import ManualLpImportDialog
from .widgets.sidebar import Sidebar
from .widgets.titlebar import TITLEBAR_HEIGHT, TitleBar
from .widgets.update_notification import UpdateNotification

#: O menor tamanho em que a janela ainda mostra tudo. A largura vem do
#: painel de campeões, que é o mais largo. A altura é medida, não
#: escolhida: com a grade de runas aberta o painel pede 621 px e a barra
#: de título come outros 46. Com os 650 de antes — de quando a grade
#: ainda não existia — o cartão de registro era empurrado para fora da
#: tela em vez de simplesmente encolher.
MINIMUM_WIDTH = 1100
MINIMUM_HEIGHT = 690

# A tela não pode virar uma borda por acidente: esta folga deixa a janela
# alcançável para mover ou redimensionar, inclusive quando há barra de tarefas.
SCREEN_MARGIN = 18
# A abertura acompanha a área útil do monitor, mas não estica a interface
# para uma faixa excessivamente larga em monitores ultrawide.
INITIAL_SCREEN_SHARE = 0.84
MAX_INITIAL_ASPECT_RATIO = 1.8
# Janela sem moldura não recebe a área de redimensionamento do Windows.
# Esta faixa devolve esse gesto sem criar uma borda visual permanente.
RESIZE_BORDER = 8


def _usable_screen_geometry(available: QRect) -> QRect:
    """A área segura em que uma janela pode abrir inteira.

    `availableGeometry()` já desconta a barra de tarefas. A margem adicional
    evita uma janela colada na borda, onde ficaria difícil recuperar o gesto
    de arrastar em uma moldura que é propositalmente invisível.
    """

    horizontal = min(SCREEN_MARGIN, max(0, (available.width() - 1) // 2))
    vertical = min(SCREEN_MARGIN, max(0, (available.height() - 1) // 2))
    return available.adjusted(horizontal, vertical, -horizontal, -vertical)


def _minimum_size_for_screen(available: QRect) -> QSize:
    """Mantém o piso confortável sem criar janela maior que a tela."""

    usable = _usable_screen_geometry(available)
    return QSize(
        min(MINIMUM_WIDTH, max(1, usable.width())),
        min(MINIMUM_HEIGHT, max(1, usable.height())),
    )


def _initial_window_geometry(available: QRect) -> QRect:
    """Uma abertura proporcional e centrada, que também cabe em telas pequenas."""

    usable = _usable_screen_geometry(available)
    minimum = _minimum_size_for_screen(available)
    width = max(minimum.width(), round(usable.width() * INITIAL_SCREEN_SHARE))
    height = max(minimum.height(), round(usable.height() * INITIAL_SCREEN_SHARE))
    # Em um ultrawide, usar 84% dos dois lados faria uma faixa horizontal
    # enorme. Preservar uma proporção próxima à da interface deixa os
    # painéis com leitura natural, e o usuário continua podendo maximizar.
    width = min(width, round(height * MAX_INITIAL_ASPECT_RATIO), usable.width())
    height = min(height, usable.height())
    x = usable.x() + max(0, (usable.width() - width) // 2)
    y = usable.y() + max(0, (usable.height() - height) // 2)
    return QRect(x, y, width, height)


class MainWindow(QWidget):
    """Moldura, navegação e o motor. Cada página cuida do seu assunto."""

    #: Ponte para ligar/desligar o motor de fora da thread da GUI.
    #: As hotkeys globais chegam pela thread do `keyboard`, que não pode
    #: tocar em widgets; a conexão em fila devolve isso à thread certa.
    engine_requested = Signal(bool)

    def __init__(self, config: Config) -> None:
        super().__init__()
        # Registra antes de aplicar o QSS: além de manter o visual igual em
        # qualquer PC, isto permite que as prévias offscreen desenhem texto.
        install_application_fonts()
        self._config = config
        self._binder = ConfigBinder(config, self)
        self._catalog: ChampionCatalog | None = None
        # Sobrevive ao consumo de `_catalog` (zerado a cada troca de fase):
        # é dele que a prévia do próximo pick tira o nome do campeão.
        self._latest_catalog: ChampionCatalog | None = None
        self._predicted_champion: int | None = None
        # A rota desta seleção, publicada pelo motor. Diz qual lista de
        # prioridade está de fato valendo, e é essa que a Central mostra
        # e deixa reordenar — reordenar a outra não mudaria a escolha.
        self._pick_position = ""
        # O equipamento da conexão atual. Nasce na thread do watcher e é
        # lido na da GUI, como o catálogo: o clique numa opção de runa só
        # deixa um bilhete nele, que o tick seguinte executa.
        self._loadout: Loadout | None = None
        self._antitoxic: MuteGuard | None = None
        # Quem copia as configurações de dentro do jogo. Nasce com a
        # conexão, na thread da vigia; até lá os botões avisam que o
        # cliente do LoL precisa estar aberto.
        self._game_sync: GameSettingsSync | None = None
        # Se o cliente do LoL está de pé agora. A referência acima
        # sobrevive à queda da conexão de propósito (ver
        # `_on_connection_changed`), então ela sozinha não diz se há
        # alguém do outro lado para ler o bilhete.
        self._connected = False
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
        # O atualizador nao toca no disco pela interface: ela mantem apenas
        # estes workers vivos ate que rede, hash e staging terminem.
        self._update_client = GithubReleaseClient()
        self._update_installation = current_installation()
        self._update_check_loader: UpdateCheckLoader | None = None
        self._update_download_loader: UpdateDownloadLoader | None = None
        self._security_check_loader: SecurityCheckLoader | None = None
        # O perfil e as partidas consultados, pelo mesmo motivo do
        # `_opgg` e do `_matchups`: sobrevivem a uma reconexão.
        self._history_source = SummonerHistorySource()
        # Os deltas de PDL vêm do cliente, não do OP.GG. Este registro
        # mantém a confirmação exata mesmo depois que os logs da Riot
        # forem rotacionados pelo Windows.
        self._lp_history = LpHistory()
        self._history_loader: HistoryLoader | None = None
        self._lp_import_loader: LpImportLoader | None = None
        # Uma confirmação de PDL pode chegar enquanto a consulta disparada
        # no fim da partida ainda está voltando. Em vez de ignorá-la, deixa
        # um segundo refresh curto na fila para não exigir clique manual.
        self._history_refresh_pending = False
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
        self._resize_edges = Qt.Edge(0)
        self._resize_origin: QPoint | None = None
        self._resize_geometry: QRect | None = None
        self._resize_cursor_active = False
        self._window_handle = None
        # Estado do motor guardado num atributo simples: `_make_engine` roda
        # na thread do watcher e não pode consultar widgets.
        self._enabled = False
        # O painel guarda algumas centenas de linhas e some ao fechar o
        # app. O arquivo é o que sobra para conferir, depois da partida,
        # qual lista foi usada e se o banimento entrou.
        self._journal = Journal(log_dir())
        # Os perfis por conta. Lidos antes da janela existir porque a
        # página de Ajustes já nasce mostrando a lista.
        self._accounts = Accounts.load()
        # A conta logada agora, segundo o cliente. Vazia até a
        # primeira leitura: sem o cliente aberto não dá para saber, e
        # inventar uma conta aqui criaria perfil sem dono.
        self._active_account = ""

        self.setWindowTitle("LoL Queue")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # O painel de campeões é naturalmente mais largo; abrir na medida
        # certa evita a primeira impressão de uma tela apertada.
        self._apply_initial_screen_geometry()
        self.setStyleSheet(STYLESHEET)

        self._build()
        self._install_window_interaction()
        self.engine_requested.connect(
            self.set_engine_enabled, Qt.ConnectionType.QueuedConnection
        )
        self._start_watcher()

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._refresh_ring)
        self._clock.start(200)
        # A integridade do pacote pode envolver centenas de DLLs. Comeca logo
        # depois de a janela aparecer, mas em uma thread propria: a protecao
        # roda em toda abertura sem atrasar a fila nem deixar a tela vazia.
        QTimer.singleShot(450, self._check_security)
        # Em uma distribuicao instalada a verificacao inicial e automatica;
        # em um clone de desenvolvimento `_check_for_update` retorna cedo.
        # Assim o aviso aparece sem exigir que o usuario encontre Ajustes.
        QTimer.singleShot(1800, self._check_for_update)

    # ---------- construção ----------

    # ---------- tamanho e moldura da janela ----------

    @staticmethod
    def _screen_at(point: QPoint | None = None):
        """A tela do cursor, com uma alternativa segura para a primeira abertura."""

        point = QCursor.pos() if point is None else point
        screen = QGuiApplication.screenAt(point)
        if screen is not None:
            return screen
        app = QGuiApplication.instance()
        return app.primaryScreen() if app is not None else None

    @classmethod
    def _available_geometry(cls, screen=None) -> QRect:
        if screen is not None:
            return screen.availableGeometry()
        # Fallback para testes muito iniciais, antes de existir QApplication.
        return QRect(0, 0, 1280, 760)

    def _apply_initial_screen_geometry(self) -> None:
        screen = self._screen_at()
        available = self._available_geometry(screen)
        self.setMinimumSize(_minimum_size_for_screen(available))
        self.setGeometry(_initial_window_geometry(available))

    def _on_screen_changed(self, screen) -> None:
        """Evita que trocar de monitor deixe a janela fora da área visível."""

        available = self._available_geometry(screen)
        usable = _usable_screen_geometry(available)
        self.setMinimumSize(_minimum_size_for_screen(available))
        if self.isMaximized():
            return

        geometry = self.geometry()
        width = min(geometry.width(), usable.width())
        height = min(geometry.height(), usable.height())
        x = min(max(geometry.x(), usable.left()), usable.right() - width + 1)
        y = min(max(geometry.y(), usable.top()), usable.bottom() - height + 1)
        fitted = QRect(x, y, width, height)
        if fitted != geometry:
            self.setGeometry(fitted)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and handle is not self._window_handle:
            self._window_handle = handle
            handle.screenChanged.connect(self._on_screen_changed)
        self._on_screen_changed(self.screen())

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_titlebar"):
            self._titlebar.set_maximized(self.isMaximized())
            if self.isMaximized():
                self._clear_window_interaction()

    def toggle_maximize(self) -> None:
        """Alterna o tamanho sem devolver a moldura nativa do Windows."""

        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._titlebar.set_maximized(self.isMaximized())

    def _install_window_interaction(self) -> None:
        """Observa a borda mesmo quando há um painel filho por cima dela."""

        self.installEventFilter(self)
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    def _resize_edges_at(self, position: QPoint):
        if self.isMaximized():
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if position.x() < RESIZE_BORDER:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - RESIZE_BORDER:
            edges |= Qt.Edge.RightEdge
        if position.y() < RESIZE_BORDER:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - RESIZE_BORDER:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _resize_cursor(edges):
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            descending = edges in (
                Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
                Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
            )
            return (
                Qt.CursorShape.SizeFDiagCursor
                if descending
                else Qt.CursorShape.SizeBDiagCursor
            )
        if horizontal:
            return Qt.CursorShape.SizeHorCursor
        if vertical:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _update_resize_cursor(self, edges) -> None:
        cursor = self._resize_cursor(edges)
        if cursor == Qt.CursorShape.ArrowCursor:
            if self._resize_cursor_active:
                self.unsetCursor()
                self._resize_cursor_active = False
            return
        self.setCursor(cursor)
        self._resize_cursor_active = True

    def _clear_window_interaction(self) -> None:
        self._drag_offset = None
        self._resize_edges = Qt.Edge(0)
        self._resize_origin = None
        self._resize_geometry = None
        self._update_resize_cursor(Qt.Edge(0))

    def _is_titlebar_drag_target(self, watched: QWidget, position: QPoint) -> bool:
        if position.y() >= TITLEBAR_HEIGHT:
            return False
        current = watched
        while current is not None and current is not self:
            if isinstance(current, QAbstractButton):
                return False
            if current is self._titlebar:
                return True
            current = current.parentWidget()
        return watched is self

    def _start_system_resize(self, edges) -> bool:
        handle = self.windowHandle()
        if handle is None:
            return False
        try:
            return bool(handle.startSystemResize(edges))
        except RuntimeError:
            return False

    def _start_system_move(self) -> bool:
        handle = self.windowHandle()
        if handle is None:
            return False
        try:
            return bool(handle.startSystemMove())
        except RuntimeError:
            return False

    def _begin_resize(self, edges, global_position: QPoint) -> None:
        if self._start_system_resize(edges):
            return
        self._resize_edges = edges
        self._resize_origin = global_position
        self._resize_geometry = self.geometry()

    def _resize_manually(self, global_position: QPoint) -> None:
        if self._resize_origin is None or self._resize_geometry is None:
            return
        geometry = QRect(self._resize_geometry)
        delta = global_position - self._resize_origin
        minimum_width = self.minimumWidth()
        minimum_height = self.minimumHeight()
        if self._resize_edges & Qt.Edge.LeftEdge:
            geometry.setLeft(
                min(geometry.left() + delta.x(), geometry.right() - minimum_width + 1)
            )
        if self._resize_edges & Qt.Edge.RightEdge:
            geometry.setRight(
                max(geometry.right() + delta.x(), geometry.left() + minimum_width - 1)
            )
        if self._resize_edges & Qt.Edge.TopEdge:
            geometry.setTop(
                min(geometry.top() + delta.y(), geometry.bottom() - minimum_height + 1)
            )
        if self._resize_edges & Qt.Edge.BottomEdge:
            geometry.setBottom(
                max(geometry.bottom() + delta.y(), geometry.top() + minimum_height - 1)
            )
        self.setGeometry(geometry)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        if not isinstance(watched, QWidget) or watched.window() is not self:
            return super().eventFilter(watched, event)
        event_type = event.type()
        mouse_events = {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }
        if event_type not in mouse_events or not hasattr(event, "globalPosition"):
            return super().eventFilter(watched, event)

        global_position = event.globalPosition().toPoint()
        position = self.mapFromGlobal(global_position)
        edges = self._resize_edges_at(position)

        if event_type == QEvent.Type.MouseMove:
            if self._resize_edges != Qt.Edge(0):
                self._resize_manually(global_position)
                return True
            if self._drag_offset is not None:
                self.move(global_position - self._drag_offset)
                return True
            self._update_resize_cursor(edges)
            return super().eventFilter(watched, event)

        if event_type == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and (
                self._resize_edges != Qt.Edge(0) or self._drag_offset is not None
            ):
                self._clear_window_interaction()
                return True
            return super().eventFilter(watched, event)

        if event.button() != Qt.MouseButton.LeftButton:
            return super().eventFilter(watched, event)
        if edges != Qt.Edge(0):
            self._begin_resize(edges, global_position)
            return True
        if event_type == QEvent.Type.MouseButtonDblClick:
            if self._is_titlebar_drag_target(watched, position):
                self.toggle_maximize()
                return True
            return super().eventFilter(watched, event)
        if self._is_titlebar_drag_target(watched, position):
            if not self._start_system_move():
                self._drag_offset = global_position - self.pos()
            return True
        return super().eventFilter(watched, event)

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
        self._titlebar = TitleBar(
            self.showMinimized,
            self.toggle_maximize,
            self.close,
        )
        right.addWidget(self._titlebar)
        self._update_notification = UpdateNotification()
        self._update_notification.update_requested.connect(self._download_update)
        right.addWidget(self._update_notification)

        self._dashboard = DashboardPage(binder=self._binder)
        self._dashboard.toggled.connect(self.toggle_engine)
        self._dashboard.rune_option_chosen.connect(self._on_rune_option_chosen)
        self._dashboard.pick_order_changed.connect(self._on_pick_order_changed)
        self._dashboard.set_pick_resolvers(self._champion_name, self._champion_icon)
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
        self._history.manual_lp_import_requested.connect(self._open_manual_lp_import)
        self._champions = ChampionsPage(self._binder)
        self._queue = QueuePage(self._binder)
        self._settings = SettingsPage(self._binder)
        self._settings.accounts.main_requested.connect(self._on_main_account)
        self._settings.accounts.forget_requested.connect(self._on_forget_account)
        self._settings.accounts.capture_requested.connect(self._on_capture_game)
        self._settings.accounts.clear_requested.connect(self._on_clear_game)
        self._settings.accounts.apply_requested.connect(self._on_apply_game)
        self._settings.security.check_requested.connect(self._check_security)
        self._settings.updates.check_requested.connect(self._check_for_update)
        self._settings.updates.download_requested.connect(self._download_update)
        if self._update_installation.is_development_checkout:
            self._settings.updates.show_unavailable(
                "Esta pasta e um repositorio de desenvolvimento. O atualizador "
                "nao a sobrescreve para preservar seu trabalho."
            )

        # A ordem tem de bater com `SECTIONS` da barra lateral: é o
        # índice do botão que escolhe a página.
        self._pages = QStackedWidget()
        for page in (
            self._dashboard,
            self._analysis,
            self._history,
            self._champions,
            self._queue,
            self._settings,
        ):
            self._pages.addWidget(self._scroll_page(page))
        right.addWidget(self._pages, 1)
        columns.addLayout(right, 1)

        # A Central e a página Campeões editam a mesma prioridade; ouvir a
        # config é o que mantém as duas contando a mesma história, venha a
        # mudança de qual das duas vier.
        self._binder.changed.connect(self._on_pick_config_changed)
        # Cada mexida nos ajustes entra também no perfil da conta
        # logada; sem isso, sair e voltar devolveria o perfil antigo
        # por cima do que o usuário acabou de escolher.
        self._binder.changed.connect(self._remember_account)
        self._binder.changed.connect(self._on_analysis_config_changed)
        self._render_pick_order()
        self._refresh_accounts()
        self._refresh_analysis_empty_state()

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
        self._sidebar.set_current(index)
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
        self._watcher.pick_scope_changed.connect(self._on_pick_scope_changed)
        self._watcher.rune_options_changed.connect(self._dashboard.set_rune_options)
        self._watcher.analysis_changed.connect(self._on_analysis_changed)
        self._watcher.identity_changed.connect(self._on_identity_changed)
        self._watcher.accounts_changed.connect(self._refresh_accounts)
        self._watcher.lp_change_captured.connect(self._on_lp_change_captured)
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
        # O mesmo guarda nos dois lados: a seleção liga o silêncio, e o
        # motor devolve as opções quando a partida acaba.
        antitoxic = MuteGuard(client, self._config, log=self._watcher.message.emit)
        # Guardado também aqui porque fechar o app no meio da partida é
        # o único caminho que escaparia do motor — e deixaria o jogador
        # mudo sem saber por quê.
        self._antitoxic = antitoxic
        engine.set_antitoxic(antitoxic)
        # A cópia das configurações de dentro do jogo. Nasce aqui porque
        # é aqui que existe o cliente da LCU; a janela só deixa bilhetes
        # nela, e quem os executa é a thread da vigia.
        sync = GameSettingsSync(
            client,
            self._accounts,
            save=self._accounts.save,
            log=self._watcher.message.emit,
            on_change=self._watcher.accounts_changed.emit,
            # As duas escrevem em `GAME_SETTINGS`. Sem esta pergunta a
            # cópia desfazia o silêncio de antes da partida, e o
            # jogador ficava com metade do chat de volta sem entender.
            hold=antitoxic.forced,
        )
        self._game_sync = sync
        engine.set_game_sync(sync)
        engine.set_lp_tracker(
            LpChangeTracker(
                client,
                self._lp_history,
                on_change=self._watcher.lp_change_captured.emit,
            )
        )
        engine.set_champ_select(
            ChampSelectController(
                client,
                self._config,
                catalog,
                log=self._watcher.message.emit,
                loadout=loadout,
                antitoxic=antitoxic,
                on_pick_predicted=self._watcher.predicted_pick_changed.emit,
                on_position=self._watcher.pick_scope_changed.emit,
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
        self._refresh_analysis_empty_state()
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
            self._on_pick_scope_changed("")
            self._dashboard.set_rune_options([], None, {})
        if phase_value == GameflowPhase.END_OF_GAME.value:
            # Pedido do usuário: o histórico não pode depender do
            # clique em "Atualizar" para saber que uma partida acabou.
            self._refresh_history()
        self._refresh_analysis_empty_state()
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
        self._render_pick_order()

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
        # O nome é lido agora, não quando a resposta chegar: até lá o
        # jogador pode ter trocado de adversário no seletor.
        opponent_name = self._analysis.opponent_name or opponent_alias
        loader = MatchupLoader(self._matchups, mine, opponent_alias, position, self)
        loader.ready.connect(self._analysis.set_matchup)
        loader.ready.connect(
            lambda _alias, found, name=opponent_name: self._install_matchup(name, found)
        )
        # Sem isto cada troca de adversário deixa uma thread morta
        # pendurada na janela pelo resto da sessão: o pai a mantém viva
        # justamente para o Python não coletá-la cedo demais.
        loader.finished.connect(lambda: self._retire_matchup_loader(loader))
        self._matchup_loader = loader
        loader.start()

    def _install_matchup(self, opponent_name: str, matchup) -> None:
        """Leva o guia ao equipamento, que o instala no tick seguinte.

        Aqui é a thread da tela; quem fala com o cliente é a do
        watcher. O guia fica guardado e vira aba de arsenal e opção de
        runa no próximo tick da seleção — o mesmo acordo do clique numa
        opção de runa.
        """
        loadout = self._loadout
        if loadout is not None and matchup is not None:
            loadout.request_matchup(opponent_name, matchup)

    def _retire_matchup_loader(self, loader) -> None:
        """Descarta o loader que terminou, se ainda for o da vez.

        Solta a referência antes de agendar a destruição: `closeEvent`
        espera nela, e esperar num objeto já destruído explodiria na
        saída do programa.
        """
        if self._matchup_loader is loader:
            self._matchup_loader = None
        loader.deleteLater()

    # ---------- verificacao de seguranca ----------

    def _check_security(self) -> None:
        if self._security_check_loader is not None:
            return
        self._settings.security.checking()
        loader = SecurityCheckLoader(self._update_installation, self)
        loader.ready.connect(self._on_security_check_ready)
        loader.finished.connect(lambda: self._retire_security_check_loader(loader))
        self._security_check_loader = loader
        loader.start()

    def _on_security_check_ready(self, report, error) -> None:
        if error is not None or report is None:
            self._settings.security.show_error()
            self._log_message("A verificacao local de seguranca nao terminou; tente novamente.")
            return
        self._settings.security.show_report(report)
        if report.has_failures:
            self._log_message("A verificacao de seguranca encontrou um problema na instalacao.")

    def _retire_security_check_loader(self, loader) -> None:
        if self._security_check_loader is loader:
            self._security_check_loader = None
        loader.deleteLater()

    # ---------- atualizacao remota ----------

    @staticmethod
    def _update_error_message(error: BaseException | None) -> str:
        """Converte falhas esperadas em frase util sem expor traceback."""

        if isinstance(error, UpdateError):
            return str(error)
        return "Ocorreu uma falha inesperada. Feche e abra o LoL Queue e tente novamente."

    def _check_for_update(self) -> None:
        if self._update_installation.is_development_checkout:
            return
        if self._update_check_loader is not None or self._update_download_loader is not None:
            return
        self._settings.updates.checking()
        self._update_notification.checking()
        loader = UpdateCheckLoader(self._update_client, self._update_installation, self)
        loader.ready.connect(self._on_update_check_ready)
        loader.finished.connect(lambda: self._retire_update_check_loader(loader))
        self._update_check_loader = loader
        loader.start()

    def _on_update_check_ready(self, offer, error) -> None:
        if isinstance(error, UpdateNotAvailable):
            self._settings.updates.show_current()
            self._update_notification.hide_notification()
            return
        if error is not None:
            self._settings.updates.show_error(self._update_error_message(error))
            self._update_notification.hide_notification()
            return
        if offer is None:
            self._settings.updates.show_error("A release oficial nao trouxe um pacote compativel.")
            self._update_notification.hide_notification()
            return
        self._settings.updates.show_offer(offer)
        self._update_notification.show_offer(offer)

    def _retire_update_check_loader(self, loader) -> None:
        if self._update_check_loader is loader:
            self._update_check_loader = None
        loader.deleteLater()

    def _download_update(self) -> None:
        if self._update_installation.is_development_checkout:
            return
        if self._update_check_loader is not None or self._update_download_loader is not None:
            return
        offer = self._settings.updates.offer
        if offer is None:
            self._check_for_update()
            return
        self._settings.updates.downloading(0, offer.artifact.size)
        self._update_notification.downloading(0, offer.artifact.size)
        loader = UpdateDownloadLoader(self._update_client, offer, self)
        loader.progress.connect(self._settings.updates.downloading)
        loader.progress.connect(self._update_notification.downloading)
        loader.ready.connect(self._on_update_download_ready)
        loader.finished.connect(lambda: self._retire_update_download_loader(loader))
        self._update_download_loader = loader
        loader.start()

    def _on_update_download_ready(self, prepared, error) -> None:
        if error is not None:
            self._settings.updates.show_error(self._update_error_message(error))
            self._update_notification.hide_notification()
            return
        if prepared is None:
            self._settings.updates.show_error("A atualizacao nao foi preparada corretamente.")
            self._update_notification.hide_notification()
            return
        self._settings.updates.preparing_restart()
        self._update_notification.preparing_restart()
        try:
            launch_prepared_update(prepared, self._update_installation)
        except Exception as exc:
            self._settings.updates.show_error(self._update_error_message(exc))
            self._update_notification.hide_notification()
            return
        self._log_message(f"Atualizacao {prepared.offer.version} conferida; reiniciando o LoL Queue.")
        # O instalador externo espera este processo sair para trocar a pasta.
        self.close()

    def _retire_update_download_loader(self, loader) -> None:
        if self._update_download_loader is loader:
            self._update_download_loader = None
        loader.deleteLater()

    def _refresh_history(self) -> None:
        """Busca perfil e partidas numa thread só dela.

        Uma consulta por vez: se já há uma rodando, o pedido novo (um
        segundo clique em "Atualizar", ou abrir a página de novo bem
        rápido) não faz nada — a que já está a caminho responde para
        os dois casos.
        """
        if self._history_loader is not None:
            self._history_refresh_pending = True
            return
        self._history.set_loading(True)
        loader = HistoryLoader(
            self._history_source,
            lp_history=self._lp_history,
            parent=self,
        )
        loader.ready.connect(self._on_history_ready)
        loader.finished.connect(lambda: self._retire_history_loader(loader))
        self._history_loader = loader
        loader.start()

    def _retire_history_loader(self, loader) -> None:
        if self._history_loader is loader:
            self._history_loader = None
            refresh_again = self._history_refresh_pending
            self._history_refresh_pending = False
        else:
            refresh_again = False
        loader.deleteLater()
        if refresh_again:
            QTimer.singleShot(0, self._refresh_history)

    def _on_history_ready(self, profile, matches) -> None:
        self._history.set_history(profile, matches)

    def _on_lp_change_captured(self, change) -> None:
        """Atualiza a lista assim que o cliente confirmar o resultado."""

        self._log_message(f"PDL registrado: {format_lp_delta(change.delta)}.")
        self._refresh_history()

    def _open_manual_lp_import(self, matches) -> None:
        """Abre a recuperação manual, sem consultar ou raspar sites externos."""

        if self._lp_import_loader is not None:
            return
        dialog = ManualLpImportDialog(matches, self._champion_name, self)
        if not dialog.exec():
            return
        rows = dialog.inputs()
        if not rows:
            return
        self._history.set_manual_importing(True)
        loader = LpImportLoader(self._lp_history, rows, self)
        loader.ready.connect(self._on_manual_lp_imported)
        loader.finished.connect(lambda: self._retire_lp_import_loader(loader))
        self._lp_import_loader = loader
        loader.start()

    def _on_manual_lp_imported(self, result) -> None:
        self._history.set_manual_importing(False)
        imported = len(result.imported)
        if imported:
            self._log_message(
                f"PDL informado salvo em {imported} "
                f"{'partida' if imported == 1 else 'partidas'}."
            )
            self._refresh_history()
        if result.rejected:
            self._log_message(
                "Alguns PDLs não puderam ser confirmados. Deixe o cliente "
                "aberto, atualize o histórico e tente de novo."
            )

    def _retire_lp_import_loader(self, loader) -> None:
        if self._lp_import_loader is loader:
            self._lp_import_loader = None
            self._history.set_manual_importing(False)
        loader.deleteLater()

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

    def _on_analysis_changed(self, champion_id, position, build, status="no_data") -> None:
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
            status,
        )

    def _on_analysis_config_changed(self, attribute: str) -> None:
        """Atualiza o motivo vazio quando a configuração muda na tela."""
        if attribute in {"auto_spells", "auto_runes", "auto_items"}:
            self._refresh_analysis_empty_state()

    def _refresh_analysis_empty_state(self) -> None:
        """Diz o próximo passo sem apagar a leitura da partida atual."""
        if self._analysis.has_analysis:
            return
        if not self._connected:
            state = "client_disconnected"
        elif not self._enabled:
            state = "automation_paused"
        elif not (
            self._config.auto_spells
            or self._config.auto_runes
            or self._config.auto_items
        ):
            state = "build_disabled"
        else:
            state = "awaiting_champion"
        self._analysis.set_empty_state(state)

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

    # ---------- ordem de escolha ----------

    def _pick_scope(self) -> str:
        """Qual lista o motor vai consultar nesta seleção.

        A rota só manda se tiver lista própria: sem ela a escolha cai na
        geral, e é a geral que a Central precisa deixar editar — senão o
        usuário reordenaria uma lista vazia e veria a partida ignorar.
        """
        position = self._pick_position
        if position and self._config.pick_priority_by_position.get(position):
            return position
        return ""

    def _scope_label(self, scope: str) -> str:
        # A automação desligada vem primeiro: sem ela nenhuma das listas
        # é consultada, e caprichar na ordem aqui não mudaria a partida.
        if not self._config.auto_pick:
            return "Escolha automática desligada — esta ordem não será usada."
        if scope:
            return f"Lista de {position_name(scope)} — é ela que vale agora."
        if self._pick_position:
            return (
                f"Lista geral — {position_name(self._pick_position)} não tem "
                "lista própria."
            )
        return "Lista geral. O primeiro disponível é o escolhido."

    def _on_pick_scope_changed(self, position: str) -> None:
        # O cliente publica a rota em maiúsculas e as chaves da config são
        # minúsculas; sem normalizar aqui, toda rota pareceria não ter
        # lista própria e a Central editaria sempre a geral.
        self._pick_position = position.casefold()
        self._render_pick_order()

    def _on_pick_config_changed(self, attribute: str) -> None:
        if attribute in ("pick_priority", "pick_priority_by_position", "auto_pick"):
            self._render_pick_order()

    def _render_pick_order(self) -> None:
        scope = self._pick_scope()
        ids = (
            self._config.pick_priority_by_position.get(scope, [])
            if scope
            else self._config.pick_priority
        )
        self._dashboard.set_pick_order(ids, self._scope_label(scope))

    def _on_pick_order_changed(self, ids: list) -> None:
        """Grava a ordem arrastada na Central na lista que está valendo."""
        scope = self._pick_scope()
        if scope:
            by_position = dict(self._config.pick_priority_by_position)
            by_position[scope] = list(ids)
            self._binder.set("pick_priority_by_position", by_position)
        else:
            self._binder.set("pick_priority", list(ids))
        # A página Campeões guarda uma cópia própria das listas; sem este
        # aviso ela continuaria mostrando a ordem antiga e o próximo
        # arrasto de lá desfaria o que foi decidido aqui.
        self._champions.set_pick_list(scope, ids)

    def _on_connection_changed(self, connected: bool) -> None:
        self._connected = connected
        self._sidebar.set_connected(connected)
        self._dashboard.ring.set_connected(connected)
        # A central de contas mostra se as ações de controles podem falar
        # com o cliente. Atualizar aqui evita um selo "aguardando" preso na
        # tela depois que o LoL já conectou (ou o contrário ao fechá-lo).
        self._refresh_accounts()
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
            self._on_pick_scope_changed("")
            self._dashboard.set_rune_options([], None, {})
        self._refresh_analysis_empty_state()

    def _refresh_ring(self) -> None:
        # Conta em toda fase, não só nas de fila. Zerado fora delas o
        # cronômetro ficava num 00:00 parado que parecia defeito.
        self._dashboard.ring.set_phase(
            self._phase, time.monotonic() - self._phase_started
        )

    # ---------- contas ----------

    def _on_identity_changed(self, identity) -> None:
        """Outra conta entrou: troca os ajustes para os dela.

        Chega da thread do watcher por sinal, que a travessia Qt entrega
        aqui na thread da janela — o único lugar onde mexer em widget é
        legítimo. A ordem importa: primeiro a config (que é o que o
        motor lê), depois o disco, depois a tela.
        """
        arrival = self._accounts.arrive(identity, self._config)
        self._active_account = arrival.key
        self._config.save()
        self._save_accounts()
        self._binder.reload()
        self._refresh_accounts()
        self._refresh_analysis_empty_state()
        if arrival.kind == ARRIVED_INHERITED:
            self._log_message(
                f"Conta {arrival.label}: ajustes copiados de {arrival.source}."
            )
        elif arrival.kind == ARRIVED_FIRST:
            self._log_message(
                f"Conta {arrival.label} marcada como principal. "
                "Os ajustes de agora ficaram guardados nela."
            )
        else:
            self._log_message(f"Conta {arrival.label}: ajustes dela recuperados.")

    def _remember_account(self, _attribute: str) -> None:
        """Guarda no perfil da conta logada o que a config tem agora."""
        if not self._active_account:
            return
        if self._accounts.remember(self._active_account, self._config):
            self._save_accounts()

    def _on_main_account(self, key: str) -> None:
        if not self._accounts.set_main(key):
            return
        self._save_accounts()
        self._refresh_accounts()
        account = self._accounts.accounts.get(key)
        if account is not None:
            self._log_message(
                f"Conta principal: {account.label}. Toda conta nova neste "
                "PC vai começar com os ajustes dela."
            )

    def _on_forget_account(self, key: str) -> None:
        account = self._accounts.accounts.get(key)
        if not self._accounts.forget(key):
            return
        self._save_accounts()
        self._refresh_accounts()
        if account is not None:
            self._log_message(f"Conta {account.label} esquecida.")

    def _on_capture_game(self, key: str) -> None:
        """Guarda as configurações de dentro do jogo da conta logada.

        Quem lê o cliente é a thread da vigia; aqui só fica o bilhete.
        A tela é redesenhada na volta seguinte do relógio das contas,
        que é quando o bilhete já virou fotografia.
        """
        if key != self._active_account:
            self._log_message(
                "A conta mudou antes de guardar os controles. Abra a conta "
                "desejada e tente novamente."
            )
            return
        if not self._ask_sync("guardar"):
            return
        self._game_sync.request_capture(key)

    def _on_clear_game(self, key: str) -> None:
        """Para de copiar: apaga a fotografia, sem tocar no cliente."""
        if not self._accounts.set_game_settings(key, {}):
            return
        self._save_accounts()
        self._refresh_accounts()
        self._log_message(
            "Configurações do jogo apagadas. Cada conta volta a usar as "
            "que o cliente do LoL já tinha nela."
        )

    def _on_apply_game(self, key: str) -> None:
        if key != self._active_account:
            self._log_message(
                "A conta mudou antes de aplicar os controles. Abra a conta "
                "desejada e tente novamente."
            )
            return
        if not self._ask_sync("aplicar"):
            return
        self._game_sync.request_apply(key)

    def _ask_sync(self, verb: str) -> bool:
        """Sem cliente conectado não há o que ler nem onde escrever.

        A cópia é feita do outro lado, pela vigia; deixar o bilhete com
        o cliente fechado seria um botão que não faz nada e não diz por
        quê.
        """
        if self._game_sync is None or not self._connected:
            self._log_message(
                f"Abra o cliente do LoL para {verb} as configurações do jogo."
            )
            return False
        return True

    def _refresh_accounts(self) -> None:
        self._settings.accounts.show_accounts(
            self._accounts.ordered(),
            self._active_account,
            self._accounts.main,
            self._connected,
        )

    def _save_accounts(self) -> None:
        """Grava os perfis. Falhar aqui não pode derrubar a janela.

        O disco pode estar cheio ou a pasta sem permissão; perder os
        perfis é ruim, mas fechar o app no meio de uma seleção por causa
        disso seria pior — e a config em uso continua valendo.
        """
        try:
            self._accounts.save()
        except OSError as exc:
            self._log_message(f"Não consegui gravar as contas: {exc}")

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
        if self._antitoxic is not None:
            # Antes de parar o watcher: o cliente da LCU é dele, e
            # depois do stop não há mais por onde escrever.
            self._antitoxic.restore()
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
        if self._lp_import_loader is not None:
            self._lp_import_loader.wait(3000)
        if self._security_check_loader is not None:
            self._security_check_loader.wait(3000)
        if self._update_check_loader is not None:
            self._update_check_loader.wait(3000)
        if self._update_download_loader is not None:
            self._update_download_loader.wait(3000)
        event.accept()
