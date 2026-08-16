from lolqueue.core.phases import GameflowPhase
from lolqueue.ui.theme import PHASE_COLORS, PHASE_LABELS, STYLESHEET, Palette


def test_palette_matches_the_spec():
    assert Palette.BACKGROUND == "#0A1428"
    assert Palette.SURFACE == "#10203A"
    assert Palette.ACCENT == "#C8AA6E"
    assert Palette.ACTIVE == "#0AC8B9"
    assert Palette.DANGER == "#E84057"
    assert Palette.TEXT == "#F0E6D2"
    assert Palette.TEXT_MUTED == "#A09B8C"


def test_every_phase_has_a_color_and_a_label():
    for phase in GameflowPhase:
        assert phase.value in PHASE_COLORS, f"cor faltando para {phase.value}"
        assert phase.value in PHASE_LABELS, f"rótulo faltando para {phase.value}"


def test_labels_are_in_portuguese_not_api_names():
    assert PHASE_LABELS[GameflowPhase.READY_CHECK.value] == "PARTIDA ENCONTRADA"
    assert PHASE_LABELS[GameflowPhase.MATCHMAKING.value] == "NA FILA"


def test_stylesheet_uses_the_palette():
    assert Palette.BACKGROUND in STYLESHEET
    assert Palette.ACCENT in STYLESHEET
