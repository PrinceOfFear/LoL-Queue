"""O juiz do arsenal: quem tem direito a virar recomendação.

Os casos aqui são números medidos de verdade no OP.GG (Ahri do meio,
Diamante+), não hipóteses — cada um deles já produziu conselho errado
na tela do app antes deste módulo existir.
"""

from lolqueue.core import ranking


def test_a_single_game_at_a_hundred_percent_loses_to_a_solid_fifty_five():
    """Taxa crua não distingue 100% de uma partida de 55% de mil.

    Banshee's Veil ganhou a única partida em que apareceu no 6º slot da
    Annie e virou o item mais recomendado da loja. O limite inferior de
    Wilson faz a amostra pequena pagar a incerteza dela.
    """
    uma_partida = ranking.wilson_lower(1, 1)
    mil_partidas = ranking.wilson_lower(550, 1000)

    assert uma_partida < mil_partidas
    # E o quanto: uma partida perfeita sustenta menos de 21% de vitória.
    assert uma_partida < 0.21


def test_an_empty_sample_is_zero_instead_of_a_crash():
    """Campo vazio é caso normal na resposta do OP.GG, não erro."""
    assert ranking.wilson_lower(0, 0) == 0.0


def test_the_bound_never_promises_more_than_the_sample_showed():
    """É um limite *inferior*: nunca fica acima da taxa observada."""
    for wins, plays in ((1, 1), (41, 68), (280, 465), (3145, 6131)):
        assert ranking.wilson_lower(wins, plays) <= wins / plays


def test_more_games_at_the_same_rate_means_more_confidence():
    """Mesma taxa, amostra maior: o intervalo aperta e o piso sobe."""
    assert ranking.wilson_lower(30, 50) < ranking.wilson_lower(300, 500)


def test_the_shortcut_from_a_rate_reconstructs_the_same_bound():
    """O resto do app guarda `win_rate`, não o total de vitórias.

    `score` existe para não obrigar cada modelo a carregar o mesmo
    número em dois campos.
    """
    assert ranking.score(41 / 68, 68) == ranking.wilson_lower(41, 68)


#: Mejai's Soulstealer no arsenal da Ahri do meio: 83,2% de vitória em
#: 107 partidas, num universo de 6557. Amostra folgada para qualquer
#: intervalo de confiança — e conselho falso, porque Mejai's é item que
#: se compra depois que a partida já está ganha.
MEJAIS = (0.832, 107, 107 / 6557)

#: Rabadon's no mesmo slot: a build de verdade, taxa modesta.
RABADON = (0.546, 2400, 0.37)


def test_an_item_bought_only_in_games_already_won_is_not_elected():
    """O caso Mejai's: o piso de amostra não basta.

    107 partidas passam em qualquer teste estatístico, e a taxa de
    83,2% é real. O que é falso é a leitura causal: a amostra não é da
    população, é de quem já estava na frente. Contra viés de
    sobrevivência não existe correção de intervalo — existe o piso de
    frequência, e é ele que barra este item.
    """
    escolhido = ranking.best([MEJAIS, RABADON], lambda o: o)

    assert escolhido == RABADON
    # E não por pouco: sozinho na lista, o Mejai's não elege ninguém.
    assert ranking.best([MEJAIS], lambda o: o) is None
    # A amostra dele passaria folgada no piso que só olha ruído.
    assert MEJAIS[1] >= ranking.MIN_PLAYS


def test_a_tiny_sample_elects_nobody_instead_of_electing_the_luckiest():
    """Sem ninguém acima dos pisos, a resposta é ``None``.

    Devolver a melhor entre as reprovadas seria dar o nome de
    recomendação a um sorteio. Quem chama decide o que fazer — no
    arsenal, repetir a mais jogada.
    """
    banshees = (1.0, 1, 0.13)
    stormsurge = (0.0, 2, 0.25)

    assert ranking.best([stormsurge, banshees], lambda o: o) is None


def test_the_ranking_orders_by_confidence_and_not_by_raw_rate():
    """Uma alternativa de 62% em 55 partidas perde para uma de 56% em
    900: seis pontos de vantagem não sobrevivem a uma amostra dessas.

    É a inversão que a taxa crua nunca faz, e é o motivo de o módulo
    existir. Quando a amostra sustenta a diferença, a ordem volta a ser
    a intuitiva — Void Staff com 60,3% em 68 passa na frente do
    Rabadon's com 54,1% em 98.
    """
    magra = (0.62, 55, 0.2)
    gorda = (0.56, 900, 0.3)

    assert ranking.ranked([magra, gorda], lambda o: o) == [gorda, magra]

    void = (41 / 68, 68, 0.16)
    rabadon = (53 / 98, 98, 0.24)
    assert ranking.ranked([rabadon, void], lambda o: o) == [void, rabadon]


def test_options_below_the_floors_drop_out_of_the_ranking():
    """`ranked` devolve só quem passou: o reprovado some da lista, não
    vai para o fim dela. Ficar no fim ainda seria estar na loja."""
    assert ranking.ranked([MEJAIS, RABADON], lambda o: o) == [RABADON]


def test_a_tie_is_broken_by_the_bigger_sample():
    """Sem critério estável o desempate viraria a ordem de inserção, e a
    mesma consulta devolveria arsenais diferentes conforme o servidor
    reordenasse a resposta."""
    pequeno = (0.55, 200, 0.2)
    grande = (0.55, 200 * 3, 0.2)

    assert ranking.ranked([pequeno, grande], lambda o: o) == [grande, pequeno]


def test_the_floors_can_be_loosened_by_the_caller():
    """Os pisos são padrão, não lei: um campo com universo menor pode
    pedir outro corte, e o módulo não conhece os campos."""
    marginal = (0.6, 10, 0.05)

    assert ranking.best([marginal], lambda o: o) is None
    assert (
        ranking.best([marginal], lambda o: o, min_plays=5, min_pick_rate=0.01)
        == marginal
    )
