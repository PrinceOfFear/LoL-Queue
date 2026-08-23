from __future__ import annotations

from ..core.phases import GameflowPhase


class Palette:
    # Os quatro tons-base continuam sendo os da identidade original. As
    # camadas extras permitem tratar cada bloco como vidro sobre a arte do Rift.
    BACKGROUND = "#0A1428"
    SURFACE = "#10203A"
    SURFACE_HIGH = "#16294A"
    BORDER = "#1E3A5F"
    ACCENT = "#C8AA6E"
    ACTIVE = "#0AC8B9"
    DANGER = "#E84057"
    TEXT = "#F0E6D2"
    TEXT_MUTED = "#A09B8C"
    INK = "#061223"
    SKY = "#74A9D6"
    GLASS = "rgba(10, 27, 49, 218)"
    GLASS_LIGHT = "rgba(21, 49, 78, 218)"


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
/* O Backdrop desenha a arte; esta é a cor de contingência do tema: {Palette.BACKGROUND}. */
#root {{ background: transparent; }}
#pageScroll {{ background: transparent; border: none; }}
#pageScroll > QWidget > QWidget {{ background: transparent; }}

/* Moldura e navegação ------------------------------------------------ */
#titlebar {{
    background: rgba(5, 16, 32, 176);
    border-bottom: 1px solid rgba(107, 147, 184, 72);
    border-top-right-radius: 18px;
}}
#windowTitle {{
    color: {Palette.SKY};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2.4px;
}}
#topPill {{
    background: rgba(10, 200, 185, 24);
    border: 1px solid rgba(10, 200, 185, 100);
    border-radius: 8px;
    color: #8BF2EA;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.3px;
    padding: 5px 9px;
}}
#windowButton, #closeButton {{
    background: transparent;
    border: none;
    color: {Palette.TEXT_MUTED};
    font-size: 19px;
    padding: 1px 12px 5px;
    border-radius: 7px;
}}
#windowButton:hover {{ background: rgba(116, 169, 214, 34); color: {Palette.TEXT}; }}
#closeButton:hover {{ background: {Palette.DANGER}; color: #FFFFFF; }}

#sidebar {{
    background: rgba(5, 17, 34, 228);
    border-right: 1px solid rgba(111, 151, 190, 82);
    border-top-left-radius: 18px;
    border-bottom-left-radius: 18px;
}}
#brandBlock {{
    background: rgba(20, 49, 77, 152);
    border: 1px solid rgba(126, 164, 198, 74);
    border-radius: 13px;
}}
#brandTitle {{
    color: {Palette.TEXT};
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1.4px;
}}
#brandSubtitle {{
    color: {Palette.ACCENT};
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 1.7px;
}}
#navButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    color: #A8B7C9;
    font-size: 13px;
    font-weight: 600;
    icon-size: 19px;
    text-align: left;
    padding: 12px 13px;
}}
#navButton:hover {{
    color: {Palette.TEXT};
    background: rgba(86, 133, 177, 30);
    border: 1px solid rgba(117, 164, 201, 56);
}}
#navButton:checked {{
    color: #F8EAC2;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(200, 170, 110, 36), stop:1 rgba(13, 50, 80, 142));
    border: 1px solid rgba(200, 170, 110, 90);
}}
#connectionDot {{
    background: rgba(8, 24, 43, 165);
    border: 1px solid rgba(111, 151, 190, 64);
    border-radius: 9px;
    color: #93A5B8;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 9px 10px;
}}
#connectionDot[state="online"] {{ color: #6EE9DF; border-color: rgba(10, 200, 185, 100); }}
#connectionDot[state="offline"] {{ color: #9AA6B5; }}

/* Cabeçalhos e superfícies ------------------------------------------ */
#pageTitle {{
    color: {Palette.TEXT};
    font-size: 25px;
    font-weight: 700;
    letter-spacing: .2px;
}}
#pageSubtitle {{
    color: #B3C0CE;
    font-size: 12px;
    padding-top: 2px;
}}
#sectionTitle {{
    color: #F0D79D;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2.2px;
}}
#card, #contentCard, #settingsCard, #championCard, #logCard {{
    background: {Palette.GLASS};
    border: 1px solid rgba(125, 162, 196, 86);
    border-radius: 14px;
}}
#contentCard, #settingsCard {{ background: rgba(9, 27, 49, 222); }}
#championCard {{ background: rgba(8, 25, 46, 225); }}
#optionCard {{
    background: rgba(28, 58, 87, 106);
    border: 1px solid rgba(127, 165, 198, 54);
    border-radius: 10px;
}}
/* Linha do histórico: a faixa lateral é a mesma leitura de relance do
   cliente do jogo — verde de vitória, vermelho de derrota — e o
   destaque de fundo marca a própria partida do jogador na tela de
   placar completo, onde as dez linhas se parecem. */
#optionCard[result="win"] {{ border-left: 3px solid {Palette.ACTIVE}; }}
#optionCard[result="lose"] {{ border-left: 3px solid {Palette.DANGER}; }}
#optionCard[target="true"] {{ background: rgba(200, 170, 110, 26); }}
/* Selo de nível sobre o retrato do campeão. */
#levelBadge {{
    background: rgba(6, 18, 35, 235);
    border: 1px solid rgba(200, 170, 110, 130);
    border-radius: 8px;
    color: {Palette.TEXT};
    font-size: 9px;
    font-weight: 800;
}}
/* Grades de ícone da linha e do placar completo: item, runa e feitiço
   de invocador. */
#itemIcon, #runeIcon, #spellIcon {{
    background: rgba(4, 16, 32, 140);
    border: 1px solid rgba(87, 133, 171, 92);
    border-radius: 5px;
}}
#cardLabel {{
    color: #B7C6D6;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
#cardValue {{
    color: {Palette.TEXT};
    font-size: 16px;
    font-weight: 650;
}}
#hint {{
    color: #AEBECD;
    font-size: 11px;
    line-height: 1.45;
}}

/* Painel ---------------------------------------------------------------- */
#heroCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(18, 47, 75, 232), stop:.48 rgba(11, 33, 60, 226),
        stop:1 rgba(7, 21, 42, 235));
    border: 1px solid rgba(159, 190, 219, 112);
    border-radius: 18px;
}}
#heroEyebrow {{
    color: #6DECE2;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2.2px;
}}
#heroHeadline {{
    color: {Palette.TEXT};
    font-size: 27px;
    font-weight: 700;
}}
#heroDetail {{
    color: #B6C6D5;
    font-size: 12px;
    line-height: 1.35;
}}
#hotkeyChip {{
    background: rgba(200, 170, 110, 24);
    border: 1px solid rgba(200, 170, 110, 75);
    border-radius: 8px;
    color: #EEDCAA;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .5px;
    padding: 7px 10px;
}}
#primaryButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #E6CE90, stop:1 {Palette.ACCENT});
    color: #071425;
    border: 1px solid #F4DFA8;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1.2px;
    padding: 13px 31px;
}}
#primaryButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FFF0BD, stop:1 #DCC17F);
}}
#primaryButton[running="true"] {{
    background: rgba(232, 64, 87, 24);
    color: #FFB9C4;
    border: 1px solid rgba(232, 64, 87, 190);
}}
#primaryButton[running="true"]:hover {{ background: {Palette.DANGER}; color: #FFFFFF; }}
#predictionChip {{
    background: rgba(10, 200, 185, 20);
    border: 1px solid rgba(10, 200, 185, 92);
    border-radius: 10px;
}}
#predictionEyebrow {{
    color: #7FE8DF;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.6px;
}}
#predictionName {{
    color: {Palette.TEXT};
    font-size: 13px;
    font-weight: 700;
}}
#runeOption {{
    background: rgba(28, 58, 87, 140);
    border: 1px solid rgba(127, 165, 198, 90);
    border-radius: 8px;
    color: {Palette.TEXT};
    font-size: 11px;
    font-weight: 700;
    padding: 7px 14px;
}}
#runeOption:hover {{
    background: rgba(10, 200, 185, 34);
    border: 1px solid rgba(10, 200, 185, 130);
}}
/* O elo que já está no cliente: marcado e sem clique, não apagado. */
#runeOption:disabled {{
    background: rgba(10, 200, 185, 26);
    border: 1px solid rgba(10, 200, 185, 120);
    color: #7FE8DF;
}}
/* A grade da página de runas ------------------------------------------- */
#runeTreeLabel {{
    color: #9FB3C6;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.5px;
}}
/* A casa escolhida é a única com moldura: é o que faz a linha ser lida de
   relance, do mesmo jeito que na tela de runas do jogo. */
#runeSlot[chosen="true"] {{
    background: rgba(10, 200, 185, 30);
    border: 1px solid rgba(10, 200, 185, 138);
    border-radius: 8px;
}}
#runeSlot[chosen="false"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}

/* Ordem de habilidades ---------------------------------------------------
   O ultimato é o único nível sem escolha — nos 6, 11 e 16 não há o que
   decidir. Marcá-lo em dourado separa a informação da decisão: o resto da
   fileira é o que o jogador de fato escolhe. */
#skillCell {{
    color: {Palette.TEXT};
    font-size: 12px;
    font-weight: 800;
    background: rgba(28, 58, 87, 150);
    border: 1px solid rgba(127, 165, 198, 60);
    border-radius: 6px;
}}
#skillCell[ultimate="true"] {{
    color: {Palette.INK};
    background: {Palette.ACCENT};
    border: 1px solid {Palette.ACCENT};
}}

/* Formulários ----------------------------------------------------------- */
QCheckBox {{
    color: #E2E8EF;
    font-size: 12px;
    spacing: 10px;
    padding: 5px 0;
}}
QCheckBox:hover {{ color: #FFFFFF; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid #587999;
    border-radius: 5px;
    background: rgba(4, 15, 31, 200);
}}
QCheckBox::indicator:hover {{ border-color: {Palette.ACTIVE}; }}
QCheckBox::indicator:checked {{
    background: {Palette.ACTIVE};
    border: 1px solid #8CF2E9;
}}
QComboBox, QDoubleSpinBox {{
    background: rgba(4, 16, 33, 218);
    border: 1px solid #385C80;
    border-radius: 8px;
    color: {Palette.TEXT};
    min-height: 20px;
    padding: 7px 30px 7px 12px;
    font-size: 12px;
}}
QComboBox:hover, QDoubleSpinBox:hover {{ border: 1px solid #6EA1C9; }}
QComboBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {Palette.ACTIVE}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    width: 7px; height: 7px;
    border-right: 1px solid {Palette.ACCENT};
    border-bottom: 1px solid {Palette.ACCENT};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: #0D213C;
    border: 1px solid #3C6186;
    selection-background-color: #1D4867;
    selection-color: #FFF3D1;
    outline: none;
    padding: 4px;
}}
QLineEdit {{
    background: rgba(4, 16, 33, 210);
    border: 1px solid #345877;
    border-radius: 8px;
    padding: 8px 11px;
    font-size: 12px;
    selection-background-color: #236B76;
}}
QLineEdit:hover {{ border-color: #5B8BB3; }}
QLineEdit:focus {{ border: 1px solid {Palette.ACTIVE}; }}
QListWidget {{
    background: rgba(3, 13, 27, 196);
    border: 1px solid #294D70;
    border-radius: 8px;
    font-size: 12px;
    outline: none;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 5px; }}
QListWidget::item:hover {{ background: rgba(64, 116, 151, 78); }}
QListWidget::item:selected {{ background: #1B5264; color: #FFF0C3; }}

/* Campeões --------------------------------------------------------------- */
#championGrid {{
    background: rgba(4, 16, 32, 120);
    border: 1px solid rgba(87, 133, 171, 92);
    border-radius: 9px;
}}
#championGrid::item {{
    padding: 3px;
    border-radius: 7px;
    font-size: 8px;
    color: #B4C0CC;
}}
#championGrid::item:hover {{ background: rgba(25, 112, 126, 116); }}
#positionTabs {{ background: transparent; }}
#positionTabs::tab {{
    background: rgba(5, 17, 33, 174);
    border: 1px solid rgba(75, 113, 148, 102);
    border-bottom: 2px solid transparent;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    color: #94A9BD;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .7px;
    padding: 8px 10px;
    margin-right: 3px;
}}
#positionTabs::tab:hover {{ color: {Palette.TEXT}; background: rgba(42, 82, 117, 135); }}
#positionTabs::tab:selected {{
    color: #FFE8A8;
    background: rgba(31, 66, 97, 220);
    border: 1px solid rgba(200, 170, 110, 118);
    border-bottom: 2px solid {Palette.ACCENT};
}}
#autoSwitch {{
    color: #AAB9C7;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .7px;
    padding: 0;
    spacing: 6px;
}}
#autoSwitch:checked {{ color: #8CEFE5; }}
#autoSwitch::indicator {{ width: 14px; height: 14px; border-radius: 4px; }}
#listNotice {{ color: #AABCCD; font-size: 10px; padding: 3px 0 5px; }}
#listNotice[alert="true"] {{ color: #F0D79D; }}
#subTitle {{ color: #9FB0C1; font-size: 9px; font-weight: 700; letter-spacing: 1px; }}

/* Registro e rolagem ----------------------------------------------------- */
#logPane {{
    background: rgba(3, 13, 27, 220);
    border: 1px solid #294D70;
    border-radius: 8px;
    color: #9FB3C5;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 10px;
}}
#logToggle {{
    background: transparent;
    border: none;
    color: #A5B8C9;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-align: left;
    padding: 6px 0;
}}
#logToggle:hover {{ color: #F2D99D; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 1px; }}
QScrollBar::handle:vertical {{ background: #456784; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #6D9ABB; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""
