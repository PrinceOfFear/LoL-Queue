"""Achar o retrato do jungler dentro do recorte do minimapa.

Os quadros são sintéticos: terreno de ruído com o ícone colado numa
posição conhecida. O que se testa não é "reconhece o Lee Sin" — isso
depende do desenho real — e sim as três propriedades de que o aviso
depende: acha onde plantamos, não acha o que não está lá, e não fala
antes de ver a mesma coisa em quadros seguidos.
"""

import numpy as np
import pytest

from lolqueue.vision.detect import (
    CONFIRM_FRAMES,
    FORGIVE_FRAMES,
    THRESHOLD,
    Detector,
    match_template,
)
from lolqueue.vision.icons import Template

LADO = 20


@pytest.fixture
def retrato() -> np.ndarray:
    rng = np.random.default_rng(3)
    return rng.integers(0, 256, (120, 120, 3), dtype=np.uint8)


@pytest.fixture
def molde(retrato) -> Template:
    return Template.from_portrait(retrato, LADO)


def terreno(size: int = 200, seed: int = 5) -> np.ndarray:
    """Um minimapa de mentira: variação em toda parte, sem ícone nenhum."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 200, (size, size, 3), dtype=np.uint8)


def plantar(
    frame: np.ndarray,
    molde: Template,
    x: int,
    y: int,
    ring: tuple[int, int, int] | None = (230, 40, 40),
    ganho: float = 1.0,
    brilho: float = 0.0,
) -> np.ndarray:
    """Cola o ícone no quadro, do jeito que o jogo desenha.

    Redondo, com anel colorido em volta, e com folga para o quadro ter
    outro brilho que o retrato original — que é o caso sempre que o
    nevoeiro ou uma habilidade acende a região.
    """
    saida = frame.copy()
    disco = molde.mask
    pintado = np.clip(molde.pixels * ganho + brilho, 0, 255)
    recorte = saida[y : y + molde.size, x : x + molde.size]
    if ring is not None:
        recorte[~disco] = ring
    recorte[disco] = pintado[disco].astype(np.uint8)
    return saida


def test_the_icon_is_found_where_it_was_planted(molde):
    quadro = plantar(terreno(), molde, 70, 40)
    achado = match_template(quadro, molde)
    assert achado is not None
    assert achado.score > 0.95
    assert (achado.x, achado.y) == (70 + LADO // 2, 40 + LADO // 2)


@pytest.mark.parametrize("canto", [(0, 0), (180, 180), (0, 180), (180, 0)])
def test_the_icon_is_found_against_every_border(molde, canto):
    """O jungler aparece na borda do minimapa como em qualquer outro lugar."""
    x, y = canto
    achado = match_template(plantar(terreno(), molde, x, y), molde)
    assert achado is not None
    assert (achado.x, achado.y) == (x + LADO // 2, y + LADO // 2)


def test_the_team_ring_does_not_spoil_the_match(molde):
    """O anel é a parte que muda de cor entre aliado e inimigo.

    Se ele entrasse na conta, o molde casaria pior justamente com o
    inimigo, que é o único que interessa.
    """
    azul = match_template(plantar(terreno(), molde, 60, 60, ring=(40, 90, 240)), molde)
    vermelho = match_template(
        plantar(terreno(), molde, 60, 60, ring=(230, 40, 40)), molde
    )
    assert azul is not None and vermelho is not None
    assert (azul.x, azul.y) == (vermelho.x, vermelho.y)
    assert abs(azul.score - vermelho.score) < 1e-9


def test_brightness_and_contrast_do_not_break_the_match(molde):
    """Correlação normalizada existe exatamente para isto.

    O ícone no minimapa fica mais escuro sob nevoeiro e mais claro sob
    um clarão de habilidade; um casamento por diferença de pixel
    quebraria nos dois casos.
    """
    quadro = plantar(terreno(), molde, 90, 30, ganho=0.6, brilho=40.0)
    achado = match_template(quadro, molde)
    assert achado is not None
    assert achado.score > THRESHOLD
    assert (achado.x, achado.y) == (90 + LADO // 2, 30 + LADO // 2)


def test_terrain_without_the_icon_matches_nothing(molde):
    assert match_template(terreno(), molde) is None


def test_another_champion_is_not_mistaken_for_this_one(molde):
    """Falar o nome errado é pior que ficar calado."""
    rng = np.random.default_rng(99)
    outro = Template.from_portrait(
        rng.integers(0, 256, (120, 120, 3), dtype=np.uint8), LADO
    )
    assert match_template(plantar(terreno(), outro, 50, 50), molde) is None


def test_a_template_bigger_than_the_frame_gives_up(molde):
    assert match_template(terreno(size=12), molde) is None


def test_a_frame_that_did_not_come_gives_up(molde):
    assert match_template(None, molde) is None


def test_a_flat_frame_does_not_divide_by_zero(molde):
    """Tela de carregamento é chapada, e chapado tem variação zero."""
    assert match_template(np.zeros((200, 200, 3), np.uint8), molde) is None


# --- confirmação temporal ----------------------------------------------


def test_one_frame_is_not_enough_to_speak(molde):
    """Um casamento solto pode ser um brilho passageiro no terreno."""
    detector = Detector([molde])
    assert detector.feed(plantar(terreno(), molde, 60, 60)) is None


def test_it_speaks_after_seeing_the_same_thing_in_a_row(molde):
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES - 1):
        assert detector.feed(quadro) is None
    achado = detector.feed(quadro)
    assert achado is not None
    assert (achado.x, achado.y) == (60 + LADO // 2, 60 + LADO // 2)


def test_a_miss_in_the_middle_starts_the_count_over(molde):
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES - 1):
        detector.feed(quadro)
    detector.feed(terreno())
    assert detector.feed(quadro) is None


def test_a_jump_across_the_map_starts_the_count_over(molde):
    """Ícone não teleporta em dois décimos de segundo.

    Dois casamentos longe um do outro são dois eventos diferentes, e
    contar os dois juntos deixaria um falso positivo virar aviso.
    """
    detector = Detector([molde])
    detector.feed(plantar(terreno(), molde, 10, 10))
    detector.feed(plantar(terreno(), molde, 170, 170))
    assert detector.feed(plantar(terreno(), molde, 170, 170)) is None


def test_after_confirmed_every_frame_reports_right_away(molde):
    """Confirmado o primeiro, seguir o ícone não pode ter atraso."""
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES):
        detector.feed(quadro)
    seguinte = plantar(terreno(), molde, 64, 62)
    achado = detector.feed(seguinte)
    assert achado is not None
    assert (achado.x, achado.y) == (64 + LADO // 2, 62 + LADO // 2)


def test_losing_sight_for_good_demands_confirmation_again(molde):
    """Sumiço longo é sumiço: o inimigo pode ter ido para outro lugar."""
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES):
        detector.feed(quadro)
    for _ in range(FORGIVE_FRAMES + 1):
        assert detector.feed(terreno()) is None
    assert detector.confirmed is False
    assert detector.feed(quadro) is None


def test_a_blink_does_not_cost_the_confirmation(molde):
    """O ícone pisca o tempo todo, e reconfirmar custa meio segundo.

    Nevoeiro passando, clarão de habilidade, outro ícone por cima: o
    inimigo some de um quadro e volta no seguinte sem ter saído do
    lugar. Cobrar três quadros novos a cada piscada atrasava o aviso
    justamente enquanto o gank acontecia.
    """
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES):
        detector.feed(quadro)
    for _ in range(FORGIVE_FRAMES):
        # Enquanto não se vê, não se afirma posição nenhuma.
        assert detector.feed(terreno()) is None
    achado = detector.feed(quadro)
    assert achado is not None
    assert (achado.x, achado.y) == (60 + LADO // 2, 60 + LADO // 2)


def test_a_blink_does_not_forgive_a_jump_across_the_map(molde):
    """Perdoar a ausência não é perdoar reaparecer do outro lado.

    Voltar longe é outro evento — provável falso positivo — e continua
    exigindo confirmação do zero.
    """
    detector = Detector([molde])
    for _ in range(CONFIRM_FRAMES):
        detector.feed(plantar(terreno(), molde, 20, 20))
    assert detector.feed(terreno()) is None
    assert detector.feed(plantar(terreno(), molde, 170, 170)) is None


def test_a_blink_before_the_confirmation_is_never_forgiven(molde):
    """A defesa contra o falso positivo fica exatamente como era.

    Três quadros seguidos, sem buraco nenhum: é isso que separa o ícone
    de verdade de um brilho que casou por acaso.
    """
    detector = Detector([molde])
    quadro = plantar(terreno(), molde, 60, 60)
    for _ in range(CONFIRM_FRAMES - 1):
        detector.feed(quadro)
    assert detector.feed(terreno()) is None
    for _ in range(CONFIRM_FRAMES - 1):
        assert detector.feed(quadro) is None
    assert detector.feed(quadro) is not None


def test_among_several_sizes_the_best_one_wins(retrato):
    """O tamanho do ícone na tela do usuário não é conhecido de antemão.

    Ele depende da escala do minimapa, que é um controle deslizante. O
    detector testa alguns tamanhos e fica com o que casar melhor.
    """
    moldes = [Template.from_portrait(retrato, n) for n in (16, LADO, 25)]
    detector = Detector(moldes)
    quadro = plantar(terreno(), moldes[1], 60, 60)
    for _ in range(CONFIRM_FRAMES):
        achado = detector.feed(quadro)
    assert achado is not None
    assert achado.size == LADO


def test_a_detector_without_templates_never_speaks():
    assert Detector([]).feed(terreno()) is None
