"""A fala do aviso, sem sintetizar nem tocar nada de verdade.

Síntese e reprodução entram injetadas: um teste que dependesse da rede
da Microsoft seria lento e instável, e um que tocasse áudio seria
impossível de rodar junto com o resto da suíte.

O que se testa aqui é o que decide se o aviso chega a tempo: a frase
sintetizada uma vez só, o cache que sobrevive à partida, e o silêncio
sem estouro e sem encher o diário quando a rede não responde.
"""

import threading

import pytest

from lolqueue.vision.voice import DEFAULT_VOICE, VOICES, Voice

FRASE = "Cuidado, Lee Sin no seu blue"
OUTRA = "Lee Sin no rio de cima"


class Sintetizador:
    """Um edge-tts de mentira: conta o que foi pedido, devolve bytes."""

    def __init__(self, falha: bool = False, estoura: bool = False) -> None:
        self.pedidos: list[tuple[str, str]] = []
        self.falha = falha
        self.estoura = estoura

    def __call__(self, text: str, voice: str) -> bytes | None:
        self.pedidos.append((text, voice))
        if self.estoura:
            raise RuntimeError("sem rede")
        if self.falha:
            return None
        return b"ID3" + text.encode("utf-8")

    @property
    def textos(self) -> list[str]:
        return [t for t, _ in self.pedidos]


class Alto_falante:
    """Toca sem tocar. Pode segurar a thread para provar a assincronia."""

    def __init__(self) -> None:
        self.tocados: list[str] = []
        self.liberar = threading.Event()
        self.liberar.set()
        self.entrou = threading.Event()

    def __call__(self, path) -> bool:
        self.entrou.set()
        self.liberar.wait(2.0)
        self.tocados.append(path.name)
        return True


def montar(tmp_path, **kwargs) -> Voice:
    kwargs.setdefault("synth", Sintetizador())
    kwargs.setdefault("play", Alto_falante())
    return Voice(directory=tmp_path, **kwargs)


@pytest.fixture
def voz(tmp_path):
    v = montar(tmp_path)
    yield v
    v.close()


# --- cache -------------------------------------------------------------


def test_a_phrase_is_synthesized_once_and_kept_on_disk(tmp_path):
    sintetizador = Sintetizador()
    voz = montar(tmp_path, synth=sintetizador)
    try:
        voz.say(FRASE)
        voz.say(FRASE)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert sintetizador.textos == [FRASE]
    assert voz.path_for(FRASE).exists()


def test_a_cached_phrase_survives_the_match(tmp_path):
    """O mesmo campeão volta na próxima partida, e o áudio já está pronto."""
    primeira = montar(tmp_path)
    try:
        primeira.say(FRASE)
        assert primeira.drain(3.0)
    finally:
        primeira.close()

    sintetizador = Sintetizador()
    segunda = montar(tmp_path, synth=sintetizador)
    try:
        segunda.say(FRASE)
        assert segunda.drain(3.0)
    finally:
        segunda.close()

    assert sintetizador.pedidos == []


def test_the_voice_name_is_part_of_the_cache_key(tmp_path):
    """Trocar de voz não pode reaproveitar o áudio da anterior."""
    a = montar(tmp_path, voice=VOICES[0])
    b = montar(tmp_path, voice=VOICES[1])
    try:
        assert a.path_for(FRASE) != b.path_for(FRASE)
    finally:
        a.close()
        b.close()


def test_an_unknown_voice_falls_back_to_the_default(tmp_path):
    voz = montar(tmp_path, voice="klingon-Neural")
    try:
        assert voz.voice == DEFAULT_VOICE
    finally:
        voz.close()


def test_a_corrupt_cached_file_is_synthesized_again(tmp_path):
    sintetizador = Sintetizador()
    voz = montar(tmp_path, synth=sintetizador)
    try:
        voz.say(FRASE)
        assert voz.drain(3.0)
        voz.path_for(FRASE).write_bytes(b"")
        voz.say(FRASE)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert sintetizador.textos == [FRASE, FRASE]


# --- síntese antecipada ------------------------------------------------


def test_priming_synthesizes_everything_before_the_first_callout(tmp_path):
    """O ponto do pré-cache: na hora do aviso não há chamada de rede.

    A síntese neural leva centenas de milissegundos. Esperar isso com o
    inimigo já no rio é o mesmo que não avisar.
    """
    sintetizador = Sintetizador()
    voz = montar(tmp_path, synth=sintetizador)
    try:
        voz.prime([FRASE, OUTRA])
        assert voz.drain(5.0)
        assert sorted(sintetizador.textos) == sorted([FRASE, OUTRA])

        sintetizador.pedidos.clear()
        voz.say(FRASE)
        assert voz.drain(3.0)
        assert sintetizador.pedidos == []
    finally:
        voz.close()


def test_priming_skips_what_is_already_on_disk(tmp_path):
    voz = montar(tmp_path)
    try:
        voz.prime([FRASE])
        assert voz.drain(5.0)
    finally:
        voz.close()

    sintetizador = Sintetizador()
    outra = montar(tmp_path, synth=sintetizador)
    try:
        outra.prime([FRASE, OUTRA])
        assert outra.drain(5.0)
    finally:
        outra.close()

    assert sintetizador.textos == [OUTRA]


def test_priming_ignores_empty_and_repeated_lines(tmp_path):
    sintetizador = Sintetizador()
    voz = montar(tmp_path, synth=sintetizador)
    try:
        voz.prime([FRASE, FRASE, "", "   ", None])
        assert voz.drain(5.0)
    finally:
        voz.close()

    assert sintetizador.textos == [FRASE]


# --- fala --------------------------------------------------------------


def test_speaking_plays_the_cached_file(tmp_path):
    alto_falante = Alto_falante()
    voz = montar(tmp_path, play=alto_falante)
    try:
        voz.say(FRASE)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert alto_falante.tocados == [voz.path_for(FRASE).name]


def test_say_returns_before_the_audio_finishes(tmp_path):
    """O laço de captura não pode parar enquanto a frase é dita.

    Cinco quadros por segundo e uma frase de dois segundos: esperar a
    fala terminar cegaria o app justamente durante o gank.
    """
    alto_falante = Alto_falante()
    alto_falante.liberar.clear()
    voz = montar(tmp_path, play=alto_falante)
    try:
        assert voz.say(FRASE) is True
        assert alto_falante.entrou.wait(3.0)
        assert alto_falante.tocados == []
        alto_falante.liberar.set()
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert alto_falante.tocados


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_empty_text_asks_nothing(voz, vazio):
    assert voz.say(vazio) is False


def test_saying_after_close_does_nothing(tmp_path):
    voz = montar(tmp_path)
    voz.close()
    assert voz.say(FRASE) is False


def test_closing_twice_is_harmless(tmp_path):
    voz = montar(tmp_path)
    voz.close()
    voz.close()


# --- silêncio ----------------------------------------------------------


def test_a_failed_synthesis_stays_quiet_instead_of_using_a_robot_voice(tmp_path):
    """Sem rede o aviso não sai.

    A alternativa seria o SAPI do Windows, e um aviso que o jogador não
    entende no meio da luta é pior que silêncio: rouba atenção e não
    entrega nada.
    """
    alto_falante = Alto_falante()
    voz = montar(tmp_path, synth=Sintetizador(falha=True), play=alto_falante)
    try:
        voz.say(FRASE)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert alto_falante.tocados == []
    assert not voz.path_for(FRASE).exists()


def test_a_synthesizer_that_raises_is_swallowed(tmp_path):
    voz = montar(tmp_path, synth=Sintetizador(estoura=True))
    try:
        voz.say(FRASE)
        assert voz.drain(3.0)
    finally:
        voz.close()


def test_the_silence_is_announced_once_and_not_every_time(tmp_path):
    """Um aviso no diário informa; um por frase vira spam."""
    recados: list[str] = []
    voz = montar(
        tmp_path,
        synth=Sintetizador(falha=True),
        on_message=recados.append,
    )
    try:
        voz.say(FRASE)
        voz.say(OUTRA)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert len(recados) == 1
    assert "voz" in recados[0].casefold()


def test_a_failed_priming_already_warns_the_journal(tmp_path):
    """O jogador descobre antes do gank, e não pelo silêncio no meio dele."""
    recados: list[str] = []
    voz = montar(
        tmp_path,
        synth=Sintetizador(falha=True),
        on_message=recados.append,
    )
    try:
        voz.prime([FRASE, OUTRA])
        assert voz.drain(5.0)
    finally:
        voz.close()

    assert len(recados) == 1


def test_a_player_that_raises_does_not_kill_the_voice_thread(tmp_path):
    """MCI recusa arquivo quebrado; a próxima frase ainda tem que tocar."""
    tocados: list[str] = []
    quebrar = {"agora": True}

    def talvez(path):
        if quebrar["agora"]:
            quebrar["agora"] = False
            raise RuntimeError("mci falhou")
        tocados.append(path.name)
        return True

    voz = montar(tmp_path, play=talvez)
    try:
        voz.say(FRASE)
        voz.say(OUTRA)
        assert voz.drain(3.0)
    finally:
        voz.close()

    assert tocados == [voz.path_for(OUTRA).name]
