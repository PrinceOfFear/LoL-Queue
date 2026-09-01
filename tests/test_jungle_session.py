"""A vigilância do jungler ligada e desligada pela partida.

O aviso do jungler não falou em nenhuma partida do jogador, e a razão
não estava na visão nem na voz: ninguém ligava as duas. Este arquivo
cobre o interruptor que faltava — quem nasce, quando, e o que acontece
quando ele apaga.
"""

from lolqueue.config import Config
from lolqueue.vision.session import JungleSession
from lolqueue.vision import session as session_module
from lolqueue.vision import voice as voice_module
from lolqueue.vision import watcher as watcher_module
from lolqueue.vision.voice import DEFAULT_VOICE, MISSING_PACKAGE_NOTICE, VOICES


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


def test_the_default_builder_passes_the_precision_selected_for_the_next_match(
    monkeypatch,
):
    """A opção é lida ao abrir a partida, como a voz e o diagnóstico."""
    captured = []

    class Voice:
        def __init__(self, name, on_message=None):
            self.name = name

    class Watcher:
        def __init__(self, voice, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(voice_module, "Voice", Voice)
    monkeypatch.setattr(watcher_module, "JungleWatcher", Watcher)

    for enabled in (True, False):
        session = JungleSession(Config(jungle_max_precision=enabled))
        session._default_build(DEFAULT_VOICE)

    assert [kwargs["max_precision"] for kwargs in captured] == [True, False]


def test_a_broken_environment_does_not_take_the_app_down():
    """Sem tela ou sem áudio, a partida segue — só sem aviso."""

    def build(voice_name):
        raise RuntimeError("sem tela")

    registro: list[str] = []
    sessao = JungleSession(Config(), log=registro.append, build=build)
    assert sessao.start() is False
    assert sessao.running is False
    assert any("jungler" in linha for linha in registro)


# ---------------------------------------------------------------------------


def test_a_missing_synthesizer_is_announced_before_the_match(monkeypatch):
    """Sem o pacote de voz, avisar na largada — não no meio do gank.

    Esta é a falha que fez o app parecer quebrado numa máquina nova: tudo
    subia, nada falava, e o diário só reclamava depois da primeira fala
    perdida — quando o aviso já não servia para nada.
    """
    monkeypatch.setattr(session_module, "synthesizer_available", lambda: False)
    sessao, _, registro = make_session()
    assert sessao.start() is True
    assert MISSING_PACKAGE_NOTICE in registro
    assert "pip install edge-tts" in MISSING_PACKAGE_NOTICE


def test_a_working_synthesizer_says_nothing(monkeypatch):
    """Quem tem o pacote não recebe recado sobre pacote."""
    monkeypatch.setattr(session_module, "synthesizer_available", lambda: True)
    sessao, _, registro = make_session()
    sessao.start()
    assert registro == []


def test_closing_during_a_start_does_not_leave_an_orphan():
    """Fechar o app na virada para "em jogo" não pode deixar rastro vivo.

    Ligar vem da vigilância de fase, desligar vem da thread da janela. Com
    as duas caindo juntas, o `stop` olhava o interruptor antes de o
    `start` ter terminado de construir, via nada para desligar e ia
    embora — e o `JungleWatcher` nascia depois, órfão, capturando tela
    com o app já fechado. Um processo que não morre.
    """
    import threading
    import time

    entrou = threading.Event()
    liberado = threading.Event()
    criados: list[tuple[VigiaFalso, VozFalsa]] = []

    def build(voice_name):
        entrou.set()
        liberado.wait(2.0)
        par = (VigiaFalso(voice_name), VozFalsa())
        criados.append(par)
        return par

    sessao = JungleSession(Config(), build=build)

    ligando = threading.Thread(target=sessao.start)
    ligando.start()
    assert entrou.wait(2.0)

    fechando = threading.Thread(target=sessao.stop)
    fechando.start()
    # Sem o ferrolho, é aqui que o `stop` passaria direto pelo interruptor
    # ainda vazio.
    time.sleep(0.05)
    liberado.set()

    ligando.join(2.0)
    fechando.join(2.0)

    vigia, voz = criados[0]
    assert vigia.starts == 1
    assert vigia.stops == 1
    assert voz.closed == 1
    assert sessao.running is False
