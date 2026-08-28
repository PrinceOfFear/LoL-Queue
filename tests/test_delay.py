"""O sorteio dos atrasos.

Existe para que o app não aja sempre no mesmo instante, e para que os
testes possam desligar o acaso pedindo uma faixa de largura zero.
"""

import pytest

from lolqueue.core.delay import sample


def nunca(low, high):
    raise AssertionError("não era para sortear nada aqui")


def test_a_range_of_zero_width_needs_no_dice():
    """Mínimo igual ao máximo é atraso fixo.

    Metade da suíte depende disto para continuar determinística.
    """
    assert sample(0.0, 0.0, rng=nunca) == 0.0
    assert sample(3.0, 3.0, rng=nunca) == 3.0


def test_the_draw_stays_inside_the_range():
    assert sample(2.0, 6.0, rng=lambda low, high: low) == 2.0
    assert sample(2.0, 6.0, rng=lambda low, high: high) == 6.0


def test_the_real_dice_respect_the_range():
    """Sem rng injetado vale o acaso de verdade, e ele tem limites."""
    valores = {sample(1.0, 4.0) for _ in range(200)}
    assert all(1.0 <= v <= 4.0 for v in valores)
    assert len(valores) > 1, "sorteio que sempre dá o mesmo não é sorteio"


def test_an_inverted_range_falls_back_to_the_floor():
    """Máximo menor que o mínimo é config torta, não motivo para explodir."""
    assert sample(5.0, 2.0, rng=nunca) == 5.0


def test_a_negative_floor_is_lifted_to_zero():
    assert sample(-3.0, -1.0, rng=nunca) == 0.0
