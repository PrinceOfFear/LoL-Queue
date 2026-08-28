"""Testes da leitura da partida em andamento.

Nada aqui abre o jogo: `parse` recebe as respostas cruas da API para
poder ser testado sem partida rodando, que é o estado normal da máquina
quando os testes rodam.
"""

from __future__ import annotations

import pytest

from lolqueue.vision.gamecfg import read_flag
from lolqueue.vision.livegame import (
    BLUE,
    JUNGLE,
    RED,
    LiveGameUnavailable,
    parse,
)


def jogador(nome, campeao, time, posicao="", punir=False):
    feitico = "Smite" if punir else "Flash"
    return {
        "riotId": nome,
        "championName": campeao,
        "team": time,
        "position": posicao,
        "summonerSpells": {
            "summonerSpellOne": {"displayName": feitico},
            "summonerSpellTwo": {"displayName": "Ignite"},
        },
    }


PARTIDA = [
    jogador("Eu#BR1", "Garen", "ORDER", "TOP"),
    jogador("Aliado#BR1", "Lee Sin", "ORDER", "JUNGLE", punir=True),
    jogador("Inimigo#BR1", "Darius", "CHAOS", "TOP"),
    jogador("Caçador#BR1", "Kha'Zix", "CHAOS", "JUNGLE", punir=True),
]


def test_reads_which_side_the_player_is_on():
    """ORDER é o time azul e CHAOS o vermelho."""
    assert parse("Eu#BR1", PARTIDA).side == BLUE
    assert parse("Inimigo#BR1", PARTIDA).side == RED


def test_reads_the_player_lane():
    """A rota sai com o nome que o jogador usaria em voz alta."""
    assert parse("Eu#BR1", PARTIDA).lane_name == "rota de cima"


def test_support_counts_as_bot_lane():
    """Suporte anda com a rota de baixo e corre os mesmos riscos."""
    partida = PARTIDA + [jogador("Sup#BR1", "Thresh", "ORDER", "UTILITY")]
    assert parse("Sup#BR1", partida).lane_name == "rota de baixo"


def test_finds_the_enemy_jungler():
    """O aliado com Punir não pode ser confundido com o inimigo."""
    jogo = parse("Eu#BR1", PARTIDA)
    assert jogo.enemy_jungler is not None
    assert jogo.enemy_jungler.champion == "Kha'Zix"


def test_smite_identifies_the_jungler_without_assigned_roles():
    """Fora da ranqueada a API não preenche a posição; o feitiço sim."""
    cega = [
        jogador("Eu#BR1", "Garen", "ORDER"),
        jogador("Caçador#BR1", "Kha'Zix", "CHAOS", punir=True),
        jogador("Outro#BR1", "Ahri", "CHAOS"),
    ]
    jogo = parse("Eu#BR1", cega)
    assert jogo.enemy_jungler.champion == "Kha'Zix"


def test_two_smites_means_no_certainty():
    """Com dois Punir no time inimigo, é melhor não chutar."""
    confusa = [
        jogador("Eu#BR1", "Garen", "ORDER"),
        jogador("A#BR1", "Kha'Zix", "CHAOS", punir=True),
        jogador("B#BR1", "Nunu", "CHAOS", punir=True),
    ]
    assert parse("Eu#BR1", confusa).enemy_jungler is None


def test_matches_the_player_even_without_the_riot_tag():
    """A API às vezes devolve o nome ativo sem a etiqueta #BR1."""
    assert parse("Eu", PARTIDA).me.champion == "Garen"


def test_unknown_player_is_an_error_not_a_guess():
    """Chutar quem é o jogador faria todo o resto sair errado."""
    with pytest.raises(LiveGameUnavailable):
        parse("Ninguém#BR1", PARTIDA)


def test_jungle_anchor_follows_the_player_side():
    """A selva do jungler azul não é a mesma do vermelho."""
    azul = parse("Aliado#BR1", PARTIDA)
    vermelho = parse("Caçador#BR1", PARTIDA)
    assert azul.lane == JUNGLE
    assert azul.my_anchor != vermelho.my_anchor
    ax, ay = azul.my_anchor
    assert ay > ax, "a selva azul fica na metade de baixo à esquerda"


def test_flipped_minimap_mirrors_only_the_red_side():
    """A opção gira o mapa para quem está de vermelho; o azul não muda."""
    azul = parse("Eu#BR1", PARTIDA, flip_minimap=True)
    vermelho = parse("Inimigo#BR1", PARTIDA, flip_minimap=True)
    assert azul.to_world(0.25, 0.75) == (0.25, 0.75)
    assert vermelho.to_world(0.25, 0.75) == pytest.approx((0.75, 0.25))


def test_without_the_flip_nobody_is_mirrored():
    """Com a opção desligada, minimapa e mundo são a mesma coisa."""
    for nome in ("Eu#BR1", "Inimigo#BR1"):
        assert parse(nome, PARTIDA).to_world(0.25, 0.75) == (0.25, 0.75)


def test_missing_config_file_falls_back_to_the_game_default(tmp_path):
    """Sem o arquivo de opções, vale o padrão do jogo e não um erro."""
    assert read_flag("FlipMiniMap", tmp_path / "nao_existe.cfg") is False


def test_reads_a_flag_from_a_config_file(tmp_path):
    """O game.cfg é um INI com seções repetidas; a leitura é linha a linha."""
    cfg = tmp_path / "game.cfg"
    cfg.write_text(
        "[General]\nFlipMiniMap=1\nMinimapScale=1.0000\n"
        "[General]\nWindowMode=0\n",
        encoding="utf-8",
    )
    assert read_flag("FlipMiniMap", cfg) is True
    assert read_flag("WindowMode", cfg) is False
