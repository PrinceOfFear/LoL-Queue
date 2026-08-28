"""Atraso sorteado antes de uma ação no cliente.

Existe por ergonomia, não por disfarce: aceitar e travar campeão no
mesmo instante em que a fase muda não deixa janela nenhuma para o
usuário mudar de ideia. Uma faixa de largura zero devolve o próprio
valor sem tocar no acaso, e é assim que os testes ficam determinísticos.
"""

from __future__ import annotations

import random
from typing import Callable

#: Sorteia um float entre dois limites. `random.uniform` na vida real;
#: nos testes, qualquer função que devolva algo previsível.
Rng = Callable[[float, float], float]


def sample(low: float, high: float, rng: Rng = random.uniform) -> float:
    """Um atraso em segundos entre `low` e `high`.

    Faixa torta não levanta erro: config vinda do disco pode ter
    qualquer coisa, e recusar aqui derrubaria o tick inteiro por causa
    de um número. Piso negativo vira zero e máximo abaixo do mínimo
    colapsa na faixa fixa do mínimo.
    """
    low = max(0.0, low)
    high = max(low, high)
    if high == low:
        return low
    return rng(low, high)
