"""Fiação da janela: o que a tela promete tem que bater com a config.

O watcher fica de fora — ele abre thread e fala com o cliente do LoL, e
nada disso é necessário para conferir a ligação entre widget e config.

A config é redirecionada para um diretório temporário: a janela grava a
cada mudança, e sem isso o teste sobrescreveria a config de verdade do
usuário.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize, Qt  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.core.lp_history import LpChange, LpImportResult  # noqa: E402
from lolqueue.ui.pages.analysis import AnalysisPage  # noqa: E402
from lolqueue.ui.pages.champions import ChampionsPage  # noqa: E402
from lolqueue.ui.pages.dashboard import DashboardPage  # noqa: E402
from lolqueue.ui.pages.history import HistoryPage  # noqa: E402
from lolqueue.ui.pages.queue import QueuePage  # noqa: E402
from lolqueue.ui.pages.settings import SettingsPage  # noqa: E402
from lolqueue.ui.widgets.sidebar import SECTIONS  # noqa: E402
from lolqueue.ui.window import (  # noqa: E402
    MAX_INITIAL_ASPECT_RATIO,
    MainWindow,
    _initial_window_geometry,
    _minimum_size_for_screen,
    _usable_screen_geometry,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(MainWindow, "_start_watcher", lambda self: None)
    config = Config(
        auto_pick=True,
        auto_ban=True,
        pick_priority=[64],
        ban_priority=[63],
    )
    return MainWindow(config)


def boxes(window, attribute):
    return window._binder.boxes(attribute)


# --- tamanho e moldura ---------------------------------------------------


def test_initial_window_geometry_fits_a_small_monitor_without_covering_it():
    available = QRect(0, 0, 1024, 768)
    usable = _usable_screen_geometry(available)
    geometry = _initial_window_geometry(available)
    minimum = _minimum_size_for_screen(available)

    assert usable.contains(geometry)
    assert geometry.width() >= minimum.width()
    assert geometry.height() >= minimum.height()


def test_initial_window_geometry_keeps_ultrawide_opening_readable():
    geometry = _initial_window_geometry(QRect(0, 0, 3440, 1440))

    assert geometry.width() <= round(geometry.height() * MAX_INITIAL_ASPECT_RATIO)


def test_initial_window_uses_the_screen_under_the_cursor(monkeypatch):
    import lolqueue.ui.window as window_module

    selected = object()
    seen = []

    class Cursor:
        @staticmethod
        def pos():
            return QPoint(1440, 90)

    class GuiApplication:
        @staticmethod
        def screenAt(point):
            seen.append(point)
            return selected

        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(window_module, "QCursor", Cursor)
    monkeypatch.setattr(window_module, "QGuiApplication", GuiApplication)

    assert MainWindow._screen_at() is selected
    assert seen == [QPoint(1440, 90)]


def test_frameless_window_recognizes_each_resize_border_and_corner(window):
    window.setGeometry(100, 100, 1200, 700)

    assert window._resize_edges_at(QPoint(0, 350)) == Qt.Edge.LeftEdge
    assert window._resize_edges_at(QPoint(1199, 350)) == Qt.Edge.RightEdge
    assert window._resize_edges_at(QPoint(600, 0)) == Qt.Edge.TopEdge
    assert window._resize_edges_at(QPoint(600, 699)) == Qt.Edge.BottomEdge
    assert window._resize_edges_at(QPoint(0, 0)) == (
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    )
    assert window._resize_edges_at(QPoint(600, 350)) == Qt.Edge(0)


def test_manual_resize_fallback_respects_the_current_minimum_size(window):
    window.setMinimumSize(QSize(900, 600))
    window.setGeometry(100, 100, 1100, 700)
    window._resize_edges = Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    window._resize_origin = QPoint(100, 100)
    window._resize_geometry = QRect(window.geometry())

    window._resize_manually(QPoint(900, 800))

    assert window.width() == 900
    assert window.height() == 600


def test_custom_titlebar_exposes_maximize_and_restore_actions(window):
    button = window._titlebar._maximize_button

    window._titlebar.set_maximized(False)
    assert button.toolTip() == "Maximizar janela"

    window._titlebar.set_maximized(True)
    assert button.toolTip() == "Restaurar tamanho da janela"


def test_resize_cursor_is_limited_to_the_window_and_clears_after_the_border(window):
    window._update_resize_cursor(Qt.Edge.LeftEdge)
    assert window.cursor().shape() == Qt.CursorShape.SizeHorCursor

    window._update_resize_cursor(Qt.Edge(0))
    assert window.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_the_same_setting_has_a_switch_next_to_its_list(window):
    """O interruptor tem que estar onde a lista está.

    Só na página de Automação ele ficava longe demais: dava para encher
    a lista inteira sem perceber que a automação estava desligada.
    """
    assert len(boxes(window, "auto_pick")) == 2
    assert len(boxes(window, "auto_ban")) == 2


def test_switching_one_switch_moves_the_other(window):
    first, second = boxes(window, "auto_pick")

    first.setChecked(False)

    assert second.isChecked() is False
    assert window._config.auto_pick is False


def test_the_switches_do_not_bounce_off_each_other(window):
    """A caixa que só reflete fica muda: reflete, não decide.

    Sem o bloqueio ela emitiria `toggled` ao ser alinhada, e o eco
    voltaria para a config para gravar de novo o que já estava lá.
    """
    first, second = boxes(window, "auto_ban")

    seen = []
    second.toggled.connect(seen.append)
    first.setChecked(False)

    assert seen == []
    assert second.isChecked() is False
    assert window._config.auto_ban is False


def test_turning_the_pick_automation_off_shows_up_on_the_list(window):
    boxes(window, "auto_pick")[0].setChecked(False)

    assert "desligada" in window._champions.pick_picker.notice()


def test_turning_the_ban_automation_off_shows_up_on_the_list(window):
    boxes(window, "auto_ban")[0].setChecked(False)

    assert "desligado" in window._champions.ban_picker.notice()


def test_emptying_the_ban_list_explains_that_the_turn_is_passed(window):
    window._champions.ban_picker.set_ids([])
    window._champions.ban_picker._emit()

    assert "passa sozinha" in window._champions.ban_picker.notice()


def test_an_empty_general_list_warns_which_lanes_pick_nothing(window):
    """A config real do usuário chegou nesse estado sem nenhum aviso."""
    window._champions.pick_picker._picker.set_ids([])
    window._champions.pick_picker._picker._emit()

    assert "TOPO" in window._champions.pick_picker.notice()


def test_the_window_saves_what_the_switches_change(window, tmp_path):
    boxes(window, "auto_pick")[0].setChecked(False)

    assert Config.load(tmp_path / "config.json").auto_pick is False


def test_every_message_is_also_written_to_the_file(window, tmp_path):
    """O painel some ao fechar o app; o arquivo é o que sobra."""
    window._log_message("Banindo Brand.")

    written = (tmp_path / "registro").glob("*.log")
    assert any("Banindo Brand." in f.read_text(encoding="utf-8") for f in written)


def test_the_log_folder_sits_next_to_the_config(window, tmp_path):
    assert window._journal.directory == tmp_path / "registro"


def test_the_analysis_empty_state_explains_each_required_step(window):
    assert window._analysis._empty_state == "client_disconnected"

    window._connected = True
    window._enabled = True
    window._refresh_analysis_empty_state()
    assert window._analysis._empty_state == "build_disabled"

    window._config.auto_items = True
    window._refresh_analysis_empty_state()
    assert window._analysis._empty_state == "awaiting_champion"


# --- opções de runa ------------------------------------------------------
#
# Quem descobre as builds é o equipamento, na thread do watcher; quem
# mostra é o painel. O clique volta pelo mesmo caminho, mas só deixa um
# bilhete: falar com o cliente do LoL a partir da thread da GUI é o que
# não pode acontecer.


class FakeLoadout:
    def __init__(self):
        self.pedidos = []
        self.confrontos = []

    def request_rune_option(self, tier):
        self.pedidos.append(tier)

    def request_matchup(self, opponent, matchup):
        self.confrontos.append((opponent, matchup))


def test_the_chosen_tier_reaches_the_loadout(window):
    loadout = FakeLoadout()
    window._loadout = loadout

    window._dashboard.rune_option_chosen.emit("master")

    assert loadout.pedidos == ["master"]


# --- navegação -----------------------------------------------------------


def test_every_sidebar_button_opens_the_page_that_matches_it(window):
    """Botão e página são montados longe um do outro, ligados só pelo índice.

    A lateral monta a partir de `SECTIONS`; a pilha monta numa tupla
    própria dentro da janela. Inserir uma seção num lugar e esquecer o
    outro não quebra nada visivelmente — só passa a abrir a página
    errada, e é o tipo de defeito que ninguém nota lendo o código.
    """
    # Casado pelo nome, de propósito: comparar com uma lista na ordem
    # que eu escrevi aqui só repetiria a ordem da pilha, e passaria
    # feliz mesmo com as duas trocadas juntas.
    esperado = {
        "Painel": DashboardPage,
        "Análise": AnalysisPage,
        "Histórico": HistoryPage,
        "Campeões": ChampionsPage,
        "Fila": QueuePage,
        "Ajustes": SettingsPage,
    }
    assert {name for name, _ in SECTIONS} == set(esperado)

    for index, (name, _icon) in enumerate(SECTIONS):
        window._sidebar.navigated.emit(index)
        # Cada página vive dentro de um QScrollArea; quem interessa é o
        # que está dentro dele.
        aberta = window._pages.currentWidget().widget()
        assert isinstance(aberta, esperado[name]), f"{name} abriu {type(aberta).__name__}"
        assert window._sidebar._group.button(index).isChecked()


def test_the_stack_has_exactly_one_page_per_section(window):
    assert window._pages.count() == len(SECTIONS)


# --- confronto -----------------------------------------------------------


class FakeLoader:
    def __init__(self):
        self.descartado = False

    def deleteLater(self):  # noqa: N802 (imita a API do Qt)
        self.descartado = True


def test_a_finished_loader_is_let_go(window):
    """Terminada a consulta, a thread não fica pendurada na janela.

    Ela nasce filha da janela para o Python não coletá-la no meio da
    busca; sem soltá-la depois, cada troca de adversário deixaria uma
    thread morta acumulada pelo resto da sessão.
    """
    loader = FakeLoader()
    window._matchup_loader = loader

    window._retire_matchup_loader(loader)

    assert window._matchup_loader is None
    assert loader.descartado


def test_a_late_loader_does_not_discard_the_current_one(window):
    """Uma consulta abandonada termina depois da que a substituiu.

    Se ela limpasse a referência ao terminar, `closeEvent` deixaria de
    esperar pela busca que ainda está rodando.
    """
    velho, atual = FakeLoader(), FakeLoader()
    window._matchup_loader = atual

    window._retire_matchup_loader(velho)

    assert window._matchup_loader is atual
    assert velho.descartado


def test_a_matchup_asked_before_a_champion_is_locked_goes_nowhere(window):
    """Sem saber quem somos, não há confronto que se possa pedir."""
    window._analysis_alias = ""

    window._analysis.matchup_requested.emit("Zed", "middle")

    assert window._matchup_loader is None


def test_a_click_without_a_client_connected_does_nothing(window):
    window._loadout = None

    window._dashboard.rune_option_chosen.emit("master")  # não levanta


def test_the_guide_of_the_matchup_reaches_the_loadout(window):
    """A tela busca o guia numa thread; quem o instala é o equipamento."""
    loadout = FakeLoadout()
    window._loadout = loadout
    guia = object()

    window._install_matchup("Ezreal", guia)

    assert loadout.confrontos == [("Ezreal", guia)]


def test_a_matchup_that_answered_nothing_installs_nothing(window):
    """O OP.GG às vezes não tem o confronto: nada a instalar."""
    loadout = FakeLoadout()
    window._loadout = loadout

    window._install_matchup("Ezreal", None)

    assert loadout.confrontos == []


def test_a_guide_without_a_client_connected_does_nothing(window):
    window._loadout = None

    window._install_matchup("Ezreal", object())  # não levanta


def test_a_reconnect_does_not_lose_the_loadout_to_a_late_disconnect(window):
    """Quem escreve o equipamento é a thread do watcher; a da GUI só lê.

    O “desconectou” chega à GUI por sinal, ou seja, com atraso. Se a
    reconexão acontecer antes de a GUI processar esse sinal — cliente do
    LoL que cai e volta enquanto a janela está ocupada pintando —, apagar
    a referência aqui apagaria a do equipamento novo, e os botões de runa
    ficariam mortos até o app ser reaberto.
    """
    novo = FakeLoadout()
    window._loadout = novo

    window._on_connection_changed(False)
    window._dashboard.rune_option_chosen.emit("master")

    assert novo.pedidos == ["master"]


def test_the_options_leave_the_screen_when_the_selection_ends(window):
    window._dashboard.set_rune_options(["master", "challenger"], "master")

    window._on_phase_changed("InProgress")

    assert window._dashboard._runes.isHidden()


def test_only_the_tiers_that_answered_become_buttons(window):
    window._dashboard.set_rune_options(["diamond_plus", "challenger"], "diamond_plus")

    options = window._dashboard._rune_options
    rotulos = [options.itemAt(i).widget().text() for i in range(options.count())]
    assert rotulos == ["Diamante+", "Desafiante"]


def test_rune_tier_buttons_carry_the_same_rank_crests_as_settings(window):
    window._dashboard.set_rune_options(["diamond_plus", "challenger"], "diamond_plus")

    options = window._dashboard._rune_options
    assert all(
        not options.itemAt(index).widget().icon().isNull()
        for index in range(options.count())
    )


def test_the_tier_already_applied_is_not_clickable(window):
    """Pedir de novo o que já está no cliente só renderia uma linha."""
    window._dashboard.set_rune_options(["diamond_plus", "challenger"], "diamond_plus")

    options = window._dashboard._rune_options
    assert options.itemAt(0).widget().isEnabled() is False
    assert options.itemAt(1).widget().isEnabled() is True


# --- filas que a Riot desligou -------------------------------------------
#
# Quem descobre é o watcher, na thread dele; quem mostra é a página, na
# thread da GUI. A entrega vai pelo mesmo caminho do catálogo: um
# atributo simples, lido na primeira troca de fase.


def test_a_queue_the_client_refuses_is_marked_on_the_selector(window):
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    combo = window._queue._combo
    assert "indisponível" in combo.itemText(combo.findData(430))


def test_the_player_hears_about_it_when_the_queue_is_his_own(window, monkeypatch):
    said = []
    monkeypatch.setattr(window, "_log_message", said.append)
    window._config.queue_id = 430
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    assert any("Normal Blind" in line for line in said)


def test_nothing_is_said_when_the_chosen_queue_works(window, monkeypatch):
    said = []
    monkeypatch.setattr(window, "_log_message", said.append)
    window._config.queue_id = 420
    window._blocked_queues = {430}

    window._on_phase_changed("None")

    assert said == []


# --- histórico e placar ---------------------------------------------------


def test_the_history_refreshes_itself_when_a_match_ends(window, monkeypatch):
    chamadas = []
    monkeypatch.setattr(window, "_refresh_history", lambda: chamadas.append(True))

    window._on_phase_changed("EndOfGame")

    assert chamadas == [True]


def test_other_phase_changes_do_not_refresh_the_history(window, monkeypatch):
    chamadas = []
    monkeypatch.setattr(window, "_refresh_history", lambda: chamadas.append(True))

    window._on_phase_changed("InProgress")

    assert chamadas == []


def test_a_finished_game_detail_loader_is_let_go(window):
    loader = FakeLoader()
    window._game_detail_loader = loader

    window._retire_game_detail_loader(loader)

    assert window._game_detail_loader is None
    assert loader.descartado


def test_a_late_game_detail_loader_does_not_discard_the_current_one(window):
    velho, atual = FakeLoader(), FakeLoader()
    window._game_detail_loader = atual

    window._retire_game_detail_loader(velho)

    assert window._game_detail_loader is atual
    assert velho.descartado


def test_open_game_detail_does_nothing_when_one_is_already_running(window):
    loader = FakeLoader()
    window._game_detail_loader = loader

    window._open_game_detail(None)

    assert window._game_detail_loader is loader


def test_a_ready_game_detail_reaches_the_history_page(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window._history, "set_game_detail", lambda detail: seen.append(detail))

    window._on_game_detail_ready("placar-falso")

    assert seen == ["placar-falso"]


def test_a_lp_refresh_requested_during_a_history_load_is_not_lost(window, monkeypatch):
    """O PDL pode chegar antes da busca do fim da partida voltar."""
    import lolqueue.ui.window as window_module

    class FakeTimer:
        scheduled = []

        @staticmethod
        def singleShot(_milliseconds, callback):  # noqa: N802 (API Qt)
            FakeTimer.scheduled.append(callback)

    monkeypatch.setattr(window_module, "QTimer", FakeTimer)
    loader = FakeLoader()
    window._history_loader = loader

    window._refresh_history()
    window._retire_history_loader(loader)

    assert loader.descartado
    assert window._history_loader is None
    assert window._history_refresh_pending is False
    assert FakeTimer.scheduled == [window._refresh_history]


def test_manual_lp_import_refreshes_only_after_a_validated_value(window, monkeypatch):
    refreshed, messages = [], []
    monkeypatch.setattr(window, "_refresh_history", lambda: refreshed.append(True))
    monkeypatch.setattr(window, "_log_message", messages.append)

    window._on_manual_lp_imported(
        LpImportResult(imported=(LpChange(998877, 420, 22, source="manual"),))
    )

    assert refreshed == [True]
    assert any("salvo" in message for message in messages)


def test_manual_lp_import_explains_when_the_lcu_cannot_confirm_a_row(window, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "_log_message", messages.append)

    window._on_manual_lp_imported(LpImportResult(rejected=1))

    assert any("não puderam" in message for message in messages)


class FakeThread:
    """Substitui `HistoryLoader`/`GameDetailLoader` sem abrir thread de verdade.

    Só precisa parecer um `QThread` o bastante para `_refresh_history`
    e `_open_game_detail` ligarem os sinais e chamarem `start()` sem
    quebrar — o que interessa ao teste é o que acontece *antes* disso.
    """

    def __init__(self, *args, **kwargs):
        self.ready = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self):
        pass


class _FakeSignal:
    def connect(self, callback):
        pass


def test_refresh_history_shows_a_loading_state_before_asking_for_data(
    window, monkeypatch
):
    """Sem isto, uma consulta lenta e uma travada pareciam a mesma coisa."""
    import lolqueue.ui.window as window_module

    monkeypatch.setattr(window_module, "HistoryLoader", FakeThread)
    marcado = []
    monkeypatch.setattr(window._history, "set_loading", marcado.append)

    window._refresh_history()

    assert marcado == [True]
def test_open_game_detail_shows_a_loading_state_before_asking_for_data(
    window, monkeypatch
):
    import lolqueue.ui.window as window_module

    monkeypatch.setattr(window_module, "GameDetailLoader", FakeThread)
    marcado = []
    monkeypatch.setattr(window._history, "set_loading", marcado.append)

    window._open_game_detail("partida-falsa")

    assert marcado == [True]
