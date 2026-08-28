"""O que a tela de campeões avisa sobre cada lista.

É lógica pura de propósito: o defeito que ela cobre é o usuário editar
uma lista que não vale para ele — a geral quando a rota tem lista
própria, uma lista qualquer com a automação desligada, ou uma rota que
não tem ninguém para escolher. Nenhum desses casos dá erro; todos
falham calados na partida.
"""

from lolqueue.ui.advice import GENERAL, ban_notice, join_names, pick_notice


def lists(general=None, **positions):
    base = {GENERAL: list(general or [])}
    for key in ("top", "jungle", "middle", "bottom", "utility"):
        base[key] = list(positions.get(key) or [])
    return base


# ---------- escolha desligada ----------


def test_the_pick_lists_say_when_the_automation_is_off():
    """Lista cheia e automação desligada não escolhe nada, sem avisar."""
    text, alert = pick_notice(GENERAL, lists(general=[64]), auto_pick=False)

    assert "desligada" in text
    assert alert is True


def test_being_off_beats_every_other_warning():
    text, _ = pick_notice("top", lists(top=[64]), auto_pick=False)

    assert "desligada" in text


# ---------- aba geral ----------


def test_the_general_list_rules_when_no_lane_overrides_it():
    text, alert = pick_notice(GENERAL, lists(general=[64]), auto_pick=True)

    assert text == "Vale para todas as rotas."
    assert alert is False


def test_the_general_list_names_the_lanes_that_ignore_it():
    text, alert = pick_notice(
        GENERAL, lists(general=[64], bottom=[21], utility=[11]), auto_pick=True
    )

    assert "ADC e SUP" in text
    assert alert is True


def test_an_empty_general_list_names_the_lanes_left_with_nobody():
    """O caso que morde de verdade: rota sorteada sem ninguém na lista.

    Com a geral vazia, cair numa rota sem lista própria significa não
    escolher campeão nenhum — e isso só aparecia durante a seleção, numa
    linha do registro que some.
    """
    text, alert = pick_notice(
        GENERAL, lists(general=[], bottom=[21], utility=[11]), auto_pick=True
    )

    assert "TOPO, SELVA e MEIO" in text
    assert alert is True


def test_an_empty_general_list_is_fine_when_every_lane_has_its_own():
    text, alert = pick_notice(
        GENERAL,
        lists(general=[], top=[1], jungle=[2], middle=[3], bottom=[4], utility=[5]),
        auto_pick=True,
    )

    assert "não é usada" in text
    assert alert is False


# ---------- abas de rota ----------


def test_a_lane_with_its_own_list_says_when_it_applies():
    text, alert = pick_notice("bottom", lists(bottom=[21]), auto_pick=True)

    assert "Atirador" in text
    assert alert is False


def test_a_lane_without_a_list_falls_back_to_the_general_one():
    text, alert = pick_notice("jungle", lists(general=[64]), auto_pick=True)

    assert "geral" in text
    assert alert is False


def test_a_lane_with_no_list_and_no_general_warns_it_picks_nothing():
    text, alert = pick_notice("jungle", lists(general=[]), auto_pick=True)

    assert "ninguém" in text
    assert alert is True


# ---------- banimento ----------


def test_the_ban_list_says_when_the_automation_is_off():
    text, alert = ban_notice([63], auto_ban=False)

    assert "desligado" in text
    assert alert is True


def test_an_empty_ban_list_explains_that_the_turn_is_passed():
    """Lista vazia com o ban ligado virou escolha, não descuido.

    O alerta some junto: pintar de vermelho o que o usuário pediu
    ensina a ignorar a cor.
    """
    text, alert = ban_notice([], auto_ban=True)

    assert "passa sozinha" in text
    assert alert is False


def test_a_filled_ban_list_explains_the_order():
    text, alert = ban_notice([63, 523], auto_ban=True)

    assert "primeiro" in text
    assert alert is False


# ---------- junção de nomes ----------


def test_names_are_joined_the_way_they_are_written():
    assert join_names(["A"]) == "A"
    assert join_names(["A", "B"]) == "A e B"
    assert join_names(["A", "B", "C"]) == "A, B e C"
    assert join_names([]) == ""
