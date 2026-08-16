from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import QUEUES, Config
from ..core.champ_select import ChampSelectController
from ..core.champions import ChampionCatalog
from ..core.engine import Engine
from ..core.icons import IconStore
from ..core.phases import GameflowPhase
from ..core.watcher import PhaseWatcher
from .icon_loader import IconLoader
from .theme import STYLESHEET
from .widgets.champion_picker import ChampionPicker
from .widgets.log_pane import LogPane
from .widgets.sidebar import Sidebar
from .widgets.status_ring import StatusRing

class MainWindow(QWidget):
    """Janela sem moldura nativa. Só desenha estado."""

    #: Ponte para ligar/desligar o motor de fora da thread da GUI.
    #: As hotkeys globais chegam pela thread do `keyboard`, que não pode
    #: tocar em widgets; a conexão em fila devolve isso à thread certa.
    engine_requested = Signal(bool)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._catalog: ChampionCatalog | None = None
        self._icons = IconStore()
        self._icon_loader: IconLoader | None = None
        self._phase = GameflowPhase.NONE.value
        self._phase_started = time.monotonic()
        self._drag_offset = None
        # Estado do motor guardado num atributo simples: `_make_engine` roda
        # na thread do watcher e não pode consultar widgets.
        self._enabled = False

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
        right.addWidget(self._build_titlebar())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_dashboard())
        self._pages.addWidget(self._build_champions_page())
        self._pages.addWidget(self._build_queue_page())
        self._pages.addWidget(self._build_settings_page())
        right.addWidget(self._pages, 1)
        columns.addLayout(right, 1)

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(46)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 12, 0)
        layout.addWidget(QLabel("LOL QUEUE"))
        layout.addStretch(1)
        for text, name, slot in (
            ("—", "windowButton", self.showMinimized),
            ("✕", "closeButton", self.close),
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(slot)
            layout.addWidget(button)
        return bar

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 10, 40, 28)
        layout.setSpacing(18)
        layout.addStretch(1)

        self._ring = StatusRing()
        layout.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignHCenter)

        self._toggle = QPushButton("INICIAR")
        self._toggle.setObjectName("primaryButton")
        self._toggle.setProperty("running", "false")
        self._toggle.clicked.connect(self.toggle_engine)
        layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignHCenter)

        hint = QLabel("F5 iniciar        F6 parar")
        hint.setObjectName("hint")
        layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)
        self._log = LogPane()
        layout.addWidget(self._log)
        return page

    def _build_champions_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(32, 14, 32, 20)
        layout.setSpacing(24)

        self._pick_picker = ChampionPicker("PRIORIDADE DE ESCOLHA")
        self._pick_picker.set_ids(self._config.pick_priority)
        self._pick_picker.changed.connect(self._on_pick_priority_changed)
        layout.addWidget(self._pick_picker, 1)

        self._ban_picker = ChampionPicker("PRIORIDADE DE BANIMENTO")
        self._ban_picker.set_ids(self._config.ban_priority)
        self._ban_picker.changed.connect(self._on_ban_priority_changed)
        layout.addWidget(self._ban_picker, 1)
        return page

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 24, 40, 28)
        layout.setSpacing(14)

        title = QLabel("FILA")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._queue_combo = QComboBox()
        for queue_id, name in QUEUES.items():
            self._queue_combo.addItem(name, queue_id)
        index = self._queue_combo.findData(self._config.queue_id)
        if index >= 0:
            self._queue_combo.setCurrentIndex(index)
        self._queue_combo.currentIndexChanged.connect(self._on_queue_changed)
        layout.addWidget(self._queue_combo)

        self._auto_queue = self._checkbox(
            "Entrar na fila e voltar a ela automaticamente", "auto_queue"
        )
        layout.addWidget(self._auto_queue)
        layout.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 24, 40, 28)
        layout.setSpacing(14)

        title = QLabel("AUTOMAÇÃO")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        layout.addWidget(
            self._checkbox("Aceitar partida automaticamente", "auto_accept")
        )
        layout.addWidget(
            self._checkbox("Escolher campeão automaticamente", "auto_pick")
        )
        layout.addWidget(self._checkbox("Banir campeão automaticamente", "auto_ban"))

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Atraso antes de travar o campeão"))
        self._delay = QDoubleSpinBox()
        self._delay.setRange(0.0, 15.0)
        self._delay.setSingleStep(0.5)
        self._delay.setSuffix(" s")
        self._delay.setValue(self._config.lock_delay_seconds)
        self._delay.valueChanged.connect(self._on_delay_changed)
        delay_row.addWidget(self._delay)
        delay_row.addStretch(1)
        layout.addLayout(delay_row)

        layout.addStretch(1)
        return page

    def _checkbox(self, label: str, attribute: str) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(getattr(self._config, attribute))
        box.toggled.connect(lambda value: self._set_config(attribute, value))
        return box

    # ---------- estado ----------

    def _set_config(self, attribute: str, value) -> None:
        setattr(self._config, attribute, value)
        self._config.save()

    def _on_queue_changed(self, index: int) -> None:
        self._set_config("queue_id", self._queue_combo.itemData(index))

    def _on_delay_changed(self, value: float) -> None:
        self._set_config("lock_delay_seconds", value)

    def _on_pick_priority_changed(self, ids: list) -> None:
        self._set_config("pick_priority", ids)

    def _on_ban_priority_changed(self, ids: list) -> None:
        self._set_config("ban_priority", ids)

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
        engine = Engine(client, self._config, log=self._watcher.message.emit)
        engine.set_champ_select(
            ChampSelectController(
                client, self._config, catalog, log=self._watcher.message.emit
            )
        )
        engine.set_enabled(self._enabled)
        return engine

    def toggle_engine(self) -> None:
        self.set_engine_enabled(not self._enabled)

    def set_engine_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._toggle.setProperty("running", "true" if enabled else "false")
        self._toggle.setText("PARAR" if enabled else "INICIAR")
        self._toggle.style().unpolish(self._toggle)
        self._toggle.style().polish(self._toggle)
        engine = self._watcher.engine
        if engine is not None:
            engine.set_enabled(enabled)
        self._log_message("Motor ligado." if enabled else "Motor desligado.")

    def _on_phase_changed(self, phase_value: str) -> None:
        self._phase = phase_value
        self._phase_started = time.monotonic()
        if self._catalog is not None:
            catalog, self._catalog = self._catalog, None
            for picker in (self._pick_picker, self._ban_picker):
                picker.set_icons(self._icons)
                picker.set_catalog(catalog)
            self._start_icon_loader(catalog)
        self._refresh_ring()

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
        for picker in (self._pick_picker, self._ban_picker):
            picker.set_icons(self._icons)
        self._log_message("Retratos prontos.")

    def _on_connection_changed(self, connected: bool) -> None:
        self._sidebar.set_connected(connected)
        self._ring.set_connected(connected)

    def _refresh_ring(self) -> None:
        # Conta em toda fase, não só nas de fila. Zerado fora delas o
        # cronômetro ficava num 00:00 parado que parecia defeito.
        self._ring.set_phase(self._phase, time.monotonic() - self._phase_started)

    def _log_message(self, message: str) -> None:
        self._log.append(message)

    # ---------- janela sem moldura ----------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 46:
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
