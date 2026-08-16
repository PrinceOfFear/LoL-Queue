from __future__ import annotations

from ..core.phases import GameflowPhase


class Palette:
    BACKGROUND = "#0A1428"
    SURFACE = "#10203A"
    SURFACE_HIGH = "#16294A"
    BORDER = "#1E3A5F"
    ACCENT = "#C8AA6E"
    ACTIVE = "#0AC8B9"
    DANGER = "#E84057"
    TEXT = "#F0E6D2"
    TEXT_MUTED = "#A09B8C"


PHASE_COLORS: dict[str, str] = {
    GameflowPhase.NONE.value: Palette.TEXT_MUTED,
    GameflowPhase.LOBBY.value: Palette.ACCENT,
    GameflowPhase.MATCHMAKING.value: Palette.ACTIVE,
    GameflowPhase.CHECKED_INTO_TOURNAMENT.value: Palette.ACCENT,
    GameflowPhase.READY_CHECK.value: Palette.DANGER,
    GameflowPhase.CHAMP_SELECT.value: Palette.ACCENT,
    GameflowPhase.GAME_START.value: Palette.ACTIVE,
    GameflowPhase.FAILED_TO_LAUNCH.value: Palette.DANGER,
    GameflowPhase.IN_PROGRESS.value: Palette.ACTIVE,
    GameflowPhase.RECONNECT.value: Palette.DANGER,
    GameflowPhase.WAITING_FOR_STATS.value: Palette.TEXT_MUTED,
    GameflowPhase.PRE_END_OF_GAME.value: Palette.TEXT_MUTED,
    GameflowPhase.END_OF_GAME.value: Palette.TEXT_MUTED,
    GameflowPhase.TERMINATED_IN_ERROR.value: Palette.DANGER,
    GameflowPhase.UNKNOWN.value: Palette.TEXT_MUTED,
}

PHASE_LABELS: dict[str, str] = {
    GameflowPhase.NONE.value: "OCIOSO",
    GameflowPhase.LOBBY.value: "NO LOBBY",
    GameflowPhase.MATCHMAKING.value: "NA FILA",
    GameflowPhase.CHECKED_INTO_TOURNAMENT.value: "TORNEIO",
    GameflowPhase.READY_CHECK.value: "PARTIDA ENCONTRADA",
    GameflowPhase.CHAMP_SELECT.value: "SELEÇÃO DE CAMPEÕES",
    GameflowPhase.GAME_START.value: "INICIANDO",
    GameflowPhase.FAILED_TO_LAUNCH.value: "FALHA AO INICIAR",
    GameflowPhase.IN_PROGRESS.value: "EM PARTIDA",
    GameflowPhase.RECONNECT.value: "RECONECTANDO",
    GameflowPhase.WAITING_FOR_STATS.value: "FINALIZANDO",
    GameflowPhase.PRE_END_OF_GAME.value: "FINALIZANDO",
    GameflowPhase.END_OF_GAME.value: "FIM DE PARTIDA",
    GameflowPhase.TERMINATED_IN_ERROR.value: "ERRO",
    GameflowPhase.UNKNOWN.value: "—",
}


STYLESHEET = f"""
* {{
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    color: {Palette.TEXT};
}}
#root {{
    background: {Palette.BACKGROUND};
    border: 1px solid {Palette.BORDER};
    border-radius: 14px;
}}
#titlebar {{
    background: transparent;
}}
#titlebar QLabel {{
    color: {Palette.TEXT_MUTED};
    font-size: 12px;
    letter-spacing: 2px;
}}
#windowButton, #closeButton {{
    background: transparent;
    border: none;
    color: {Palette.TEXT_MUTED};
    font-size: 15px;
    padding: 4px 12px;
    border-radius: 6px;
}}
#windowButton:hover {{
    background: {Palette.SURFACE_HIGH};
    color: {Palette.TEXT};
}}
#closeButton:hover {{
    background: {Palette.DANGER};
    color: #FFFFFF;
}}
#sidebar {{
    background: {Palette.SURFACE};
    border-right: 1px solid {Palette.BORDER};
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
}}
#navButton {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: {Palette.TEXT_MUTED};
    font-size: 13px;
    text-align: left;
    padding: 12px 18px;
}}
#navButton:hover {{
    color: {Palette.TEXT};
    background: {Palette.SURFACE_HIGH};
}}
#navButton:checked {{
    color: {Palette.ACCENT};
    border-left: 3px solid {Palette.ACCENT};
    background: {Palette.SURFACE_HIGH};
}}
#connectionDot {{
    font-size: 11px;
    color: {Palette.TEXT_MUTED};
    padding: 10px 18px;
}}
#primaryButton {{
    background: {Palette.ACCENT};
    color: {Palette.BACKGROUND};
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 13px 40px;
}}
#primaryButton:hover {{ background: #D9BE83; }}
#primaryButton[running="true"] {{
    background: transparent;
    color: {Palette.DANGER};
    border: 1px solid {Palette.DANGER};
}}
#primaryButton[running="true"]:hover {{
    background: {Palette.DANGER};
    color: #FFFFFF;
}}
#hint {{
    color: {Palette.TEXT_MUTED};
    font-size: 11px;
    letter-spacing: 1px;
}}
#card {{
    background: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER};
    border-radius: 10px;
}}
#sectionTitle {{
    color: {Palette.ACCENT};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
}}
QCheckBox {{ font-size: 13px; spacing: 10px; padding: 6px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {Palette.BORDER};
    border-radius: 5px;
    background: {Palette.BACKGROUND};
}}
QCheckBox::indicator:checked {{
    background: {Palette.ACCENT};
    border: 1px solid {Palette.ACCENT};
}}
QComboBox, QDoubleSpinBox {{
    background: {Palette.BACKGROUND};
    border: 1px solid {Palette.BORDER};
    border-radius: 7px;
    padding: 8px 12px;
    font-size: 13px;
}}
QComboBox:hover, QDoubleSpinBox:hover {{ border: 1px solid {Palette.ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER};
    selection-background-color: {Palette.SURFACE_HIGH};
    outline: none;
}}
QLineEdit {{
    background: {Palette.BACKGROUND};
    border: 1px solid {Palette.BORDER};
    border-radius: 7px;
    padding: 7px 11px;
    font-size: 12px;
    selection-background-color: {Palette.SURFACE_HIGH};
}}
QLineEdit:focus {{ border: 1px solid {Palette.ACCENT}; }}
QListWidget {{
    background: {Palette.BACKGROUND};
    border: 1px solid {Palette.BORDER};
    border-radius: 7px;
    font-size: 13px;
    outline: none;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 5px; }}
QListWidget::item:selected {{
    background: {Palette.SURFACE_HIGH};
    color: {Palette.ACCENT};
}}
#championGrid {{ background: {Palette.SURFACE}; }}
#championGrid::item {{
    padding: 2px;
    border-radius: 6px;
    font-size: 8px;
    color: {Palette.TEXT_MUTED};
}}
#championGrid::item:hover {{ background: {Palette.SURFACE_HIGH}; }}
#positionTabs {{ background: transparent; }}
#positionTabs::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {Palette.TEXT_MUTED};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 7px 9px;
    margin-right: 2px;
}}
#positionTabs::tab:hover {{ color: {Palette.TEXT}; }}
#positionTabs::tab:selected {{
    color: {Palette.ACCENT};
    border-bottom: 2px solid {Palette.ACCENT};
}}
#subTitle {{
    color: {Palette.TEXT_MUTED};
    font-size: 9px;
    letter-spacing: 1px;
}}
#logPane {{
    background: {Palette.BACKGROUND};
    border: 1px solid {Palette.BORDER};
    border-radius: 7px;
    color: {Palette.TEXT_MUTED};
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 11px;
}}
#logToggle {{
    background: transparent;
    border: none;
    color: {Palette.TEXT_MUTED};
    font-size: 11px;
    letter-spacing: 1px;
    text-align: left;
    padding: 6px 0;
}}
#logToggle:hover {{ color: {Palette.ACCENT}; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {Palette.BORDER}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {Palette.TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""
