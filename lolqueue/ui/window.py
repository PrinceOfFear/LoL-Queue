from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Config, log_dir, queue_name
from ..core.champ_select import ChampSelectController
from ..core.champions import ChampionCatalog
from ..core.engine import Engine
from ..core.icons import IconStore
from ..core.journal import Journal
from ..core.loadout import Loadout
from ..core.opgg import OpggSource
from ..core.phases import GameflowPhase
from ..core.queues import unavailable_queues
from ..core.watcher import PhaseWatcher
from .binding import ConfigBinder
from .icon_loader import IconLoader
from .pages.champions import ChampionsPage
from .pages.dashboard import DashboardPage
from .pages.queue import QueuePage
from .pages.settings import SettingsPage
from .theme import STYLESHEET
from .widgets.sidebar import Sidebar
from .widgets.titlebar import TITLEBAR_HEIGHT, TitleBar


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
        # Filas que a Riot desligou nesta região. Descobertas na thread
        # do watcher e lidas na da GUI, igual ao catálogo.
        self._blocked_queues: set[int] | None = None
        # Vive fora do motor de propósito: assim o que já foi
        # consultado sobrevive a uma reconexão com o cliente.
        self._opgg = OpggSource()
        self._icons = IconStore()
        self._icon_loader: IconLoader | None = None
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
        self.resize(980, 640)
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

        root = QWidget()
        root.setObjectName("root")
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
        self._dashboard.set_log_folder(self._journal.directory)
        self._champions = ChampionsPage(self._binder)
        self._queue = QueuePage(self._binder)

        self._pages = QStackedWidget()
        for page in (
            self._dashboard,
            self._champions,
            self._queue,
            SettingsPage(self._binder),
        ):
            self._pages.addWidget(page)
        right.addWidget(self._pages, 1)
        columns.addLayout(right, 1)

    def _navigate(self, index: int) -> None:
        self._pages.setCurrentIndex(index)

    # ---------- motor ----------

    def _start_watcher(self) -> None:
        self._watcher = PhaseWatcher(self._make_engine)
        self._watcher.phase_changed.connect(self._on_phase_changed)
        self._watcher.connection_changed.connect(self._on_connection_changed)
        self._watcher.message.connect(self._log_message)
        self._watcher.start()

    def _make_engine(self, client) -> Engine:
        """Chamado na thread do watcher a cada reconexão."""
        catalog = ChampionCatalog(client)
        catalog.load()
        self._catalog = catalog
        self._blocked_queues = unavailable_queues(client)
        engine = Engine(client, self._config, log=self._watcher.message.emit)
        engine.set_champ_select(
            ChampSelectController(
                client,
                self._config,
                catalog,
                log=self._watcher.message.emit,
                loadout=Loadout(
                    client,
                    self._config,
                    catalog,
                    log=self._watcher.message.emit,
                    source=self._opgg,
                ),
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
            self._start_icon_loader(catalog)
        if self._blocked_queues is not None:
            blocked, self._blocked_queues = self._blocked_queues, None
            self._show_blocked_queues(blocked)
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
        """Busca os retratos que faltam, uma vez por conexão."""
        ids = [champion_id for champion_id, _ in catalog.all()]
        if self._icon_loader is not None or not self._icons.missing(ids):
            return
        self._log_message("Baixando os retratos dos campeões…")
        self._icon_loader = IconLoader(ids, self._icons, self)
        self._icon_loader.done.connect(self._on_icons_ready)
        self._icon_loader.start()

    def _on_icons_ready(self) -> None:
        self._champions.set_icons(self._icons)
        self._log_message("Retratos prontos.")

    def _on_connection_changed(self, connected: bool) -> None:
        self._sidebar.set_connected(connected)
        self._dashboard.ring.set_connected(connected)

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
        event.accept()
