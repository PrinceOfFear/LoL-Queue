"""A vigilância do jungler ligada e desligada pela partida.

O aviso do jungler não falou em nenhuma partida do jogador, e a razão
não estava na visão nem na voz: ninguém ligava as duas. Este arquivo
cobre o interruptor que faltava — quem nasce, quando, e o que acontece
quando ele apaga.
"""

from lolqueue.config import Config
from lolqueue.vision.session import JungleSession
from lolqueue.vision.voice import DEFAULT_VOICE, VOICES


class VigiaFalso:
    def __init__(self, voice_name: str):
        self.voice_name = voice_name
        self.starts = 0
        self.stops = 0

    def start(self) -> bool:
        self.starts += 1
        return True

    def stop(self) -> None:
        self.stops += 1


class VozFalsa:
    def __init__(self):
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def make_session(config=None):
    criados: list[tuple[VigiaFalso, VozFalsa]] = []

    def build(voice_name):
        par = (VigiaFalso(voice_name), VozFalsa())
        criados.append(par)
        return par

    registro: list[str] = []
    sessao = JungleSession(config or Config(), log=registro.append, build=build)
    return sessao, criados, registro


def test_the_match_opens_the_watch():
    sessao, criados, _ = make_session()
    assert sessao.start() is True
    assert sessao.running is True
    assert criados[0][0].starts == 1


def test_starting_twice_does_not_open_two():
    sessao, criados, _ = make_session()
    sessao.start()
    assert sessao.start() is False
    assert len(criados) == 1


def test_the_end_of_the_match_closes_the_watch_and_the_voice():
    sessao, criados, _ = make_session()
    sessao.start()
    sessao.stop()
    vigia, voz = criados[0]
    assert (vigia.stops, voz.closed) == (1, 1)
    assert sessao.running is False


def test_stopping_without_starting_is_harmless():
    sessao, criados, _ = make_session()
    sessao.stop()
    assert criados == []


def test_the_next_match_picks_the_voice_chosen_meanwhile():
    """Trocar a voz nas configurações não deveria exigir religar o app."""
    outra = next(v for v in VOICES if v != DEFAULT_VOICE)
    config = Config()
    sessao, criados, _ = make_session(config)
    sessao.start()
    sessao.stop()
    config.jungle_voice = outra
    sessao.start()
    assert [vigia.voice_name for vigia, _ in criados] == [DEFAULT_VOICE, outra]


def test_a_voice_the_config_does_not_know_falls_back():
    config = Config()
    config.jungle_voice = "nao-existe"
    sessao, criados, _ = make_session(config)
    sessao.start()
    assert criados[0][0].voice_name == DEFAULT_VOICE


def test_a_broken_environment_does_not_take_the_app_down():
    """Sem tela ou sem áudio, a partida segue — só sem aviso."""

    def build(voice_name):
        raise RuntimeError("sem tela")

    registro: list[str] = []
    sessao = JungleSession(Config(), log=registro.append, build=build)
    assert sessao.start() is False
    assert sessao.running is False
    assert any("jungler" in linha for linha in registro)
