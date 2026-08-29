"""Testes da frase falada.

O que estes testes protegem é a reclamação que originou o módulo: o app
falava como se todo jogador fosse o do meio. A mesma posição do jungler
inimigo tem que gerar frases diferentes para o jogador da rota de cima e
para o da rota de baixo.
"""

from __future__ import annotations

import pytest

from lolqueue.vision.callout import LONGE, MEDIO, PERTO, announce, map_end
from lolqueue.vision.livegame import parse
from lolqueue.vision.zones import CAMPS, classify

# Posições de referência, todas conferidas contra a textura oficial.
SAPO_AZUL = (0.146, 0.435)
KRUGS_AZUL = (0.567, 0.825)
BLUE_VERMELHO = (0.742, 0.533)


def jogador(nome, time, posicao):
    return {
        "riotId": nome,
        "championName": "Garen",
        "team": time,
        "position": posicao,
        "summonerSpells": {},
    }


def partida(posicao, time="ORDER"):
    outro = "CHAOS" if time == "ORDER" else "ORDER"
    return parse(
        "Eu#BR1",
        [
            jogador("Eu#BR1", time, posicao),
            jogador("Jg#BR1", outro, "JUNGLE"),
        ],
    )


def test_the_same_sighting_reads_differently_per_lane():
    """O ponto do mapa é o mesmo; o risco não."""
    de_cima = announce("Lee Sin", *SAPO_AZUL, game=partida("TOP"))
    de_baixo = announce("Lee Sin", *SAPO_AZUL, game=partida("BOTTOM"))
    assert de_cima.urgency == PERTO
    assert de_baixo.urgency == LONGE
    assert de_cima.text != de_baixo.text


def test_enemy_in_your_half_and_your_end_is_always_urgent():
    """Distância em linha reta mente num mapa cheio de parede.

    O sapo do lado azul fica a 0.30 da rota de cima em linha reta, mas a
    segundos de caminhada. O que decide é metade do mapa mais ponta.
    """
    assert announce("Lee Sin", *SAPO_AZUL, game=partida("TOP")).urgency == PERTO
    assert announce("Lee Sin", *KRUGS_AZUL, game=partida("BOTTOM")).urgency == PERTO


def test_the_other_side_of_the_map_is_good_news():
    """Saber que o jungler está longe vale tanto quanto saber que veio."""
    aviso = announce("Lee Sin", *KRUGS_AZUL, game=partida("TOP"))
    assert aviso.urgency == LONGE
    assert "longe de você" in aviso.text


def test_blind_pick_does_not_get_a_made_up_distance():
    """Fila cega chega sem rota, e sem rota não existe "longe de você".

    A API só preenche `position` em ranqueada e draft. Antes disso, a
    âncora caía no centro do mapa e o app tratava todo mundo como se
    fosse o meio: o top de fila cega ouvia que o jungler estava longe
    dele — soando como permissão para empurrar a rota — enquanto o
    jungler estava na torre dele. Sem saber onde o jogador está, o aviso
    diz onde o inimigo apareceu e para por aí.
    """
    cega = partida("")
    aviso = announce("Lee Sin", *KRUGS_AZUL, game=cega)
    assert cega.anchor_is_a_guess is True
    assert aviso.urgency == MEDIO
    assert "longe de você" not in aviso.text
    assert "Lee Sin" in aviso.text


def test_a_declared_lane_still_measures_the_distance():
    """A correção acima não pode calar quem tem rota declarada."""
    assert partida("TOP").anchor_is_a_guess is False
    assert announce("Lee Sin", *KRUGS_AZUL, game=partida("TOP")).urgency == LONGE


def test_urgent_callouts_start_with_the_warning():
    """Quem está prestes a morrer precisa da primeira palavra, não da última."""
    aviso = announce("Lee Sin", *SAPO_AZUL, game=partida("TOP"))
    assert aviso.text.startswith("Cuidado,")


def test_the_territory_owner_follows_the_listener_side():
    """A mesma selva é sua ou dele conforme o time de quem ouve."""
    azul = announce("Lee Sin", *SAPO_AZUL, game=partida("TOP", "ORDER"))
    vermelho = announce("Lee Sin", *SAPO_AZUL, game=partida("TOP", "CHAOS"))
    assert "seu sapo" in azul.text
    assert "sapo dele" in vermelho.text


def test_a_jungler_player_is_not_alarmed_by_his_own_home():
    """Para quem joga na selva, estar na selva não é notícia.

    O tom só sobe quando o inimigo invade a metade dele.
    """
    jg = partida("JUNGLE")
    invasao = announce("Lee Sin", *SAPO_AZUL, game=jg)
    fora = announce("Lee Sin", *BLUE_VERMELHO, game=jg)
    assert invasao.urgency == PERTO
    assert fora.urgency != PERTO


def test_it_still_speaks_without_a_live_game():
    """Ficar mudo porque a API não respondeu é o pior resultado."""
    aviso = announce("Lee Sin", *SAPO_AZUL)
    assert "no sapo" in aviso.text
    assert aviso.urgency == MEDIO


def test_it_names_the_enemy_even_without_a_champion():
    """Sem saber o campeão, ainda dá para avisar."""
    assert "jungler inimigo" in announce("", 0.5, 0.5).text


def test_flipped_minimap_does_not_send_the_player_the_wrong_way():
    """Com o mapa girado, o pixel muda mas o lugar continua o mesmo."""
    normal = partida("TOP", "CHAOS")
    girado = parse(
        "Eu#BR1",
        [jogador("Eu#BR1", "CHAOS", "TOP"), jogador("Jg#BR1", "ORDER", "JUNGLE")],
        flip_minimap=True,
    )
    mx, my = SAPO_AZUL
    assert announce("Lee Sin", mx, my, game=normal).zone_key == "gromp"
    # Girado, o mesmo lugar do mundo aparece no pixel oposto.
    assert announce("Lee Sin", 1 - mx, 1 - my, game=girado).zone_key == "gromp"


@pytest.mark.parametrize("chave, x, y, dono", [(c[0], c[1], c[2], c[3]) for c in CAMPS])
def test_every_camp_is_reachable_by_name(chave, x, y, dono):
    """Nenhum campo pode ser engolido por rota, rio ou selva genérica."""
    assert announce("Lee Sin", x, y).zone_key == chave


def test_map_end_splits_on_the_baron_dragon_axis():
    """A ponta do mapa é a mesma conta que separa os dois rios."""
    assert map_end(0.24, 0.24) == "top"
    assert map_end(0.78, 0.78) == "bot"


# --- síntese antecipada ------------------------------------------------


def test_the_catalog_covers_every_place_classify_can_return():
    """A lista de zonas é varrida, não escrita à mão.

    Se um campo novo entrar em `zones` e a lista ficasse para trás, a
    falta apareceria como uma frase muda no meio de um gank.
    """
    from lolqueue.vision.callout import zone_catalog
    from lolqueue.vision.zones import classify

    catalogo = {(z.key, z.side) for z in zone_catalog()}
    for i in range(61):
        for j in range(61):
            zona = classify(i / 60, j / 60)
            assert (zona.key, zona.side) in catalogo


def test_every_phrase_announce_can_say_is_pre_synthesized():
    """O pré-cache só serve se nada escapar dele."""
    from lolqueue.vision.callout import all_phrases, phrase
    from lolqueue.vision.zones import classify

    prontas = set(all_phrases("Lee Sin", 1))
    for i in range(41):
        for j in range(41):
            zona = classify(i / 40, j / 40)
            for urgencia in (PERTO, MEDIO, LONGE):
                assert phrase("Lee Sin", zona, 1, urgencia) in prontas


def test_the_players_own_territory_is_synthesized_first():
    """A preparação leva segundos; o gank pode chegar no meio dela."""
    from lolqueue.vision.callout import all_phrases

    frases = all_phrases("Lee Sin", 1)
    primeira_dele = next(i for i, t in enumerate(frases) if "dele" in t)
    ultima_sua = max(i for i, t in enumerate(frases) if "seu" in t or "sua" in t)
    assert ultima_sua < primeira_dele


def test_phrases_are_not_repeated():
    from lolqueue.vision.callout import all_phrases

    frases = all_phrases("Lee Sin", 1)
    assert len(frases) == len(set(frases))


def test_a_nameless_jungler_still_gets_phrases():
    """O nome pode não ter chegado ainda; o aviso não espera por ele."""
    from lolqueue.vision.callout import all_phrases

    frases = all_phrases("", 0)
    assert frases
    assert all("jungler inimigo" in t for t in frases)


def test_a_warning_carries_the_side_of_the_zone_it_names():
    """Quem compara dois avisos precisa do lado junto com a chave."""
    aviso = announce("Lee Sin", 0.19, 0.63)
    assert aviso.zone_key == "jungle_top"
    assert aviso.zone_side == classify(0.19, 0.63).side


def test_a_warning_read_on_a_border_is_not_firm():
    """O aviso leva consigo se o ponto que o gerou estava numa divisa.

    Quem decide falar não tem as coordenadas na mão — só a frase. Sem
    esse campo, a única defesa contra o tremor em cima da fronteira
    seria esperar quadros, e esperar atrasa também o aviso que estava
    certo desde o primeiro.
    """
    assert announce("Lee Sin", 0.44, 0.30).firm is False
    assert announce("Lee Sin", 0.34, 0.30).firm is True


def test_a_hand_made_warning_is_firm_by_default():
    """Só `announce` sabe medir a divisa; ninguém mais precisa saber."""
    from lolqueue.vision.callout import Callout

    aviso = Callout("Lee Sin no rio", MEDIO, "rio_cima")
    assert aviso.firm is True
    assert aviso.zone_side == 0
