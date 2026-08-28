"""O guia de confronto.

Diferente do resto do OP.GG, esta ferramenta responde JSON de verdade.
E responde só em inglês: com `pt_BR` volta vazia, sem erro — por isso o
pedido fixa `en_US` e há teste para isso não ser "melhorado" depois.

As respostas aqui foram encurtadas de capturas do servidor real (Yasuo
no meio, contra Zed e contra Malzahar).
"""

import json

from lolqueue.core.matchup import Matchup, MatchupSource, parse_matchup

ZED = {
    "data": {
        "opponent_champion_tip": "Block Razor Shuriken (Q) with Wind Wall [W].",
        "lane_advantage_champion": "Zed",
        "lane_solo_kill_advantage_champion": "EVEN",
        "recommended_play_style": "even",
    }
}

MALZAHAR = {
    "data": {
        "opponent_champion_tip": "Do not stay stand near minions!",
        "lane_advantage_champion": "EVEN",
        "lane_solo_kill_advantage_champion": "Yasuo",
        "recommended_play_style": "aggressive",
    }
}


# --- a leitura ------------------------------------------------------------


def test_it_reads_the_written_tip():
    found = parse_matchup(ZED, "Yasuo", "Zed")

    assert found.tip == "Block Razor Shuriken (Q) with Wind Wall [W]."


def test_the_favoured_champion_comes_by_name():
    found = parse_matchup(ZED, "Yasuo", "Zed")

    assert found.lane_advantage == "Zed"


def test_an_even_lane_leaves_the_advantage_empty():
    """`EVEN` é palavra do OP.GG, e não deve vazar para a tela.

    Vazia, quem desenha decide o que dizer — "parelha", um travessão —
    sem precisar conhecer o vocabulário do servidor.
    """
    found = parse_matchup(ZED, "Yasuo", "Zed")

    assert found.solo_kill_advantage == ""


def test_the_two_advantages_are_read_apart():
    """Rota e duelo isolado são perguntas diferentes, e discordam.

    Contra Malzahar o Yasuo empata a rota e ainda assim ganha o duelo
    — juntar os dois num campo só perderia exatamente essa distinção.
    """
    found = parse_matchup(MALZAHAR, "Yasuo", "Malzahar")

    assert found.lane_advantage == ""
    assert found.solo_kill_advantage == "Yasuo"


def test_the_play_style_is_said_in_portuguese():
    assert parse_matchup(MALZAHAR, "Yasuo", "Malzahar").play_style == "Agressivo"


def test_a_style_we_do_not_know_is_kept_as_it_came():
    """Palavra nova do servidor aparece crua, e não some.

    Some seria pior: o campo ficaria vazio sem ninguém saber por quê.
    """
    outro = {"data": dict(ZED["data"], recommended_play_style="reckless")}

    assert parse_matchup(outro, "Yasuo", "Zed").play_style == "reckless"


def test_an_answer_without_a_tip_is_no_answer():
    """Sem dica sobra só quem leva vantagem, que não diz o que fazer."""
    vazio = {"data": dict(ZED["data"], opponent_champion_tip="")}

    assert parse_matchup(vazio, "Yasuo", "Zed") is None


def test_an_answer_without_data_is_no_answer():
    assert parse_matchup({}, "Yasuo", "Zed") is None
    assert parse_matchup({"data": None}, "Yasuo", "Zed") is None


# --- a fonte --------------------------------------------------------------


class FakeSend:
    def __init__(self, answer=ZED, fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        if self.fail:
            raise OSError("sem rede")
        return json.dumps(self.answer)


def test_it_asks_for_both_champions_and_the_lane():
    send = FakeSend()

    MatchupSource(send=send).fetch("Yasuo", "Zed", "middle")

    assert send.calls[0]["my_champion"] == "yasuo"
    assert send.calls[0]["opponent_champion"] == "zed"
    assert send.calls[0]["position"] == "MID"


def test_a_name_with_an_apostrophe_is_asked_in_a_form_the_server_accepts():
    """`Kai'Sa` e `Kog'Maw` voltavam "Invalid champion specified".

    Como toda falha daqui vira ``None``, o guia de confronto sumia da
    tela sem dizer por quê — e sumia sempre, para todo campeão de nome
    composto. Era o pior tipo de bug: silencioso e permanente.
    """
    send = FakeSend()

    MatchupSource(send=send).fetch("Kai'Sa", "Kog'Maw", "bottom")

    assert send.calls[0]["my_champion"] == "kaisa"
    assert send.calls[0]["opponent_champion"] == "kogmaw"


def test_a_name_with_a_space_becomes_a_single_word():
    send = FakeSend()

    MatchupSource(send=send).fetch("Lee Sin", "Nunu & Willump", "jungle")

    assert send.calls[0]["my_champion"] == "lee_sin"
    assert send.calls[0]["opponent_champion"] == "nunu_willump"


def test_the_screen_still_reads_the_name_the_player_knows():
    """O slug é como o servidor quer ouvir, não como a tela escreve."""
    found = MatchupSource(send=FakeSend()).fetch("Kai'Sa", "Kog'Maw", "bottom")

    assert (found.my_champion, found.opponent) == ("Kai'Sa", "Kog'Maw")


def test_it_always_asks_in_english():
    """Em pt_BR esta ferramenta responde vazio, sem erro nenhum.

    A tentação de pedir em português é óbvia — a dica é texto que o
    usuário vai ler. Mas o servidor devolve zero caractere, e o
    resultado seria a seção sumir da tela sem explicação.
    """
    send = FakeSend()

    MatchupSource(send=send).fetch("Yasuo", "Zed", "middle")

    assert send.calls[0]["lang"] == "en_US"


def test_the_answer_becomes_a_matchup():
    found = MatchupSource(send=FakeSend()).fetch("Yasuo", "Zed", "middle")

    assert isinstance(found, Matchup)
    assert found.opponent == "Zed"


def test_a_network_failure_is_not_an_explosion():
    assert MatchupSource(send=FakeSend(fail=True)).fetch("Yasuo", "Zed", "middle") is None


def test_junk_instead_of_json_is_not_an_explosion():
    class Junk:
        calls = []

        def __call__(self, arguments):
            return "isto não é json"

    assert MatchupSource(send=Junk()).fetch("Yasuo", "Zed", "middle") is None


def test_a_lane_the_source_does_not_know_is_not_asked():
    send = FakeSend()

    assert MatchupSource(send=send).fetch("Yasuo", "Zed", "") is None
    assert send.calls == []


def test_the_same_pair_is_only_asked_once():
    send = FakeSend()
    source = MatchupSource(send=send)

    source.fetch("Yasuo", "Zed", "middle")
    source.fetch("Yasuo", "Zed", "middle")

    assert len(send.calls) == 1


def test_a_different_opponent_is_asked_again():
    send = FakeSend()
    source = MatchupSource(send=send)

    source.fetch("Yasuo", "Zed", "middle")
    source.fetch("Yasuo", "Malzahar", "middle")

    assert len(send.calls) == 2


def test_a_failed_answer_is_not_remembered():
    """Guardar a falha condenaria o par pelo resto da sessão."""
    send = FakeSend(fail=True)
    source = MatchupSource(send=send)

    source.fetch("Yasuo", "Zed", "middle")
    source.fetch("Yasuo", "Zed", "middle")

    assert len(send.calls) == 2
