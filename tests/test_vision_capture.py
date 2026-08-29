"""A captura de tela: escolha de monitor, recorte, política e fallback.

Nada aqui toca GPU nem abre o jogo. O que dá para testar sem placa de
vídeo é justamente o que erra em silêncio: escolher o monitor errado,
trocar a ordem dos canais, servir um quadro velho quando não devia, e
ficar mudo quando a captura não funciona.
"""

from types import SimpleNamespace

from pathlib import Path

import numpy as np
import pytest

from lolqueue.vision import duplication, watcher as watcher_module
from lolqueue.vision.capture import DUPLICATION_TRIAL_GRABS, ScreenGrabber
from lolqueue.vision.duplication import DuplicationGrabber, DuplicationUnavailable
from lolqueue.vision.gamecfg import exclusive_fullscreen
from lolqueue.vision.watcher import (
    BLIND_MESSAGE,
    BLIND_SECONDS,
    BLIND_SPOKEN,
    FULLSCREEN_HINT,
    FULLSCREEN_SPOKEN,
    GAME_RETRY_SECONDS,
    GAME_TRIES_BEFORE_WARNING,
    JUNGLER_REREADS,
    NOTE_NO_GAME,
    NOTE_NO_JUNGLER,
    NOTE_NO_CONFIG,
    NOTE_NO_MINIMAP,
    RELOCATE_SECONDS,
    JungleWatcher,
)
from lolqueue.vision.window import Rect

ULTRAWIDE = Rect(0, 0, 3440, 1440)
SECUNDARIO = Rect(-1600, 0, 1600, 900)


# ---------- escolha do monitor ----------


def test_picks_the_monitor_that_contains_the_rectangle():
    escolha = duplication.pick_output([SECUNDARIO, ULTRAWIDE], Rect(760, 156, 1920, 1080))
    assert escolha == 1


def test_picks_the_monitor_with_negative_coordinates_when_the_game_is_there():
    escolha = duplication.pick_output([ULTRAWIDE, SECUNDARIO], Rect(-1400, 100, 800, 600))
    assert escolha == 1


def test_picks_the_larger_overlap_when_the_window_straddles_two_monitors():
    # Janela a cavalo: 100px no secundário, 700px no ultrawide.
    escolha = duplication.pick_output([SECUNDARIO, ULTRAWIDE], Rect(-100, 100, 800, 600))
    assert escolha == 1


def test_reports_no_monitor_when_the_rectangle_is_off_screen():
    assert duplication.pick_output([ULTRAWIDE], Rect(9000, 9000, 100, 100)) is None


def test_reports_no_monitor_when_there_are_none():
    assert duplication.pick_output([], Rect(0, 0, 10, 10)) is None


# ---------- recorte e conversão de cor ----------


def _desktop_bgra(width: int, height: int) -> np.ndarray:
    """Um desktop falso em BGRA, com cada pixel identificável."""
    quadro = np.zeros((height, width, 4), dtype=np.uint8)
    quadro[:, :, 0] = 10  # azul
    quadro[:, :, 1] = 20  # verde
    quadro[:, :, 2] = 30  # vermelho
    quadro[:, :, 3] = 255  # alfa, que precisa sumir
    return quadro


def test_dropping_the_alpha_and_swapping_channels_gives_rgb():
    recorte = duplication.crop(_desktop_bgra(8, 8), Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert recorte.shape == (8, 8, 3)
    assert recorte.dtype == np.uint8
    # BGRA (10, 20, 30, 255) tem que virar RGB (30, 20, 10).
    assert tuple(int(v) for v in recorte[0, 0]) == (30, 20, 10)


def test_the_crop_lands_on_the_requested_screen_rectangle():
    quadro = _desktop_bgra(100, 50)
    quadro[10, 20] = (1, 2, 3, 255)
    recorte = duplication.crop(quadro, Rect(0, 0, 100, 50), Rect(20, 10, 4, 4))
    assert recorte.shape == (4, 4, 3)
    assert tuple(int(v) for v in recorte[0, 0]) == (3, 2, 1)


def test_the_crop_accounts_for_the_monitor_origin():
    quadro = _desktop_bgra(100, 50)
    quadro[5, 5] = (7, 8, 9, 255)
    # Monitor à esquerda do principal: coordenada de tela -1595 é a
    # coluna 5 do quadro.
    recorte = duplication.crop(quadro, Rect(-1600, 0, 100, 50), Rect(-1595, 5, 2, 2))
    assert tuple(int(v) for v in recorte[0, 0]) == (9, 8, 7)


def test_a_crop_that_falls_outside_the_monitor_is_refused():
    quadro = _desktop_bgra(100, 50)
    assert duplication.crop(quadro, Rect(0, 0, 100, 50), Rect(90, 0, 20, 10)) is None
    assert duplication.crop(quadro, Rect(0, 0, 100, 50), Rect(-5, 0, 10, 10)) is None


def test_an_empty_rectangle_yields_no_crop():
    quadro = _desktop_bgra(100, 50)
    assert duplication.crop(quadro, Rect(0, 0, 100, 50), Rect(0, 0, 0, 10)) is None


# ---------- política de timeout e perda de acesso ----------


class _RoteiroDXGI(DuplicationGrabber):
    """Um grabber cujo diálogo com a GPU é um roteiro fixo.

    Só `_pull` fala com o DXGI; trocá-lo deixa a política — cache,
    timeout, perda de acesso — exposta a um teste sem placa de vídeo.
    """

    def __init__(self, roteiro, origin=ULTRAWIDE):
        super().__init__()
        self._roteiro = list(roteiro)
        self._origin = origin
        self._pending_first = False
        self.recriacoes = 0

    def _pull(self, rect):
        if not self._roteiro:
            return duplication.FAILED, None
        return self._roteiro.pop(0)

    def _drop_duplication(self):
        self.recriacoes += 1
        origem = self._origin
        super()._drop_duplication()
        # A remontagem real acontece no `_ensure_duplication`; aqui basta
        # o monitor voltar a ser conhecido.
        self._origin = origem


def _quadro(valor: int, width=200, height=100) -> np.ndarray:
    quadro = np.zeros((height, width, 4), dtype=np.uint8)
    quadro[:, :, :3] = valor
    return quadro


def test_a_new_frame_is_cropped_and_returned():
    grabber = _RoteiroDXGI([(duplication.NEW_FRAME, _quadro(90))])
    recorte = grabber.grab(Rect(0, 0, 20, 20))
    assert recorte is not None
    assert int(recorte[0, 0, 0]) == 90


def test_an_unchanged_screen_serves_the_last_good_frame_instead_of_nothing():
    grabber = _RoteiroDXGI(
        [(duplication.NEW_FRAME, _quadro(90)), (duplication.NO_CHANGE, None)]
    )
    grabber.grab(Rect(0, 0, 20, 20))
    segundo = grabber.grab(Rect(0, 0, 20, 20))
    assert segundo is not None, "timeout do DXGI não é falha: a tela só não mudou"
    assert int(segundo[0, 0, 0]) == 90


def test_an_unchanged_screen_with_no_frame_yet_gives_nothing():
    grabber = _RoteiroDXGI([(duplication.NO_CHANGE, None)])
    assert grabber.grab(Rect(0, 0, 20, 20)) is None


def test_losing_access_drops_the_duplication_and_recovers_on_the_next_call():
    grabber = _RoteiroDXGI(
        [
            (duplication.NEW_FRAME, _quadro(90)),
            (duplication.ACCESS_LOST, None),
            (duplication.NEW_FRAME, _quadro(120)),
        ]
    )
    grabber.grab(Rect(0, 0, 20, 20))
    assert grabber.grab(Rect(0, 0, 20, 20)) is None
    assert grabber.recriacoes == 1
    depois = grabber.grab(Rect(0, 0, 20, 20))
    assert depois is not None and int(depois[0, 0, 0]) == 120


def test_a_lost_frame_is_never_served_after_access_was_lost():
    grabber = _RoteiroDXGI(
        [
            (duplication.NEW_FRAME, _quadro(90)),
            (duplication.ACCESS_LOST, None),
            (duplication.NO_CHANGE, None),
        ]
    )
    grabber.grab(Rect(0, 0, 20, 20))
    grabber.grab(Rect(0, 0, 20, 20))
    assert grabber.grab(Rect(0, 0, 20, 20)) is None


def test_a_failure_is_reported_as_no_frame():
    grabber = _RoteiroDXGI([(duplication.FAILED, None)])
    assert grabber.grab(Rect(0, 0, 20, 20)) is None


def test_an_exception_from_the_gpu_never_escapes():
    class _Explode(_RoteiroDXGI):
        def _pull(self, rect):
            raise OSError("driver sumiu no meio da partida")

    assert _Explode([]).grab(Rect(0, 0, 20, 20)) is None


def test_the_first_black_frame_after_duplicating_is_discarded():
    """O DXGI entrega a textura zerada na primeira aquisição.

    Confirmado ao vivo nesta máquina. Guardar esse quadro faria o vigia
    concluir "tela ilegível" no começo de toda partida — exatamente o
    diagnóstico errado que este módulo veio corrigir.
    """
    grabber = _RoteiroDXGI(
        [(duplication.NEW_FRAME, _quadro(0)), (duplication.NEW_FRAME, _quadro(77))]
    )
    grabber._pending_first = True
    assert grabber.grab(Rect(0, 0, 20, 20)) is None
    segundo = grabber.grab(Rect(0, 0, 20, 20))
    assert segundo is not None and int(segundo[0, 0, 0]) == 77


def test_a_useful_first_frame_is_kept():
    grabber = _RoteiroDXGI([(duplication.NEW_FRAME, _quadro(77))])
    grabber._pending_first = True
    recorte = grabber.grab(Rect(0, 0, 20, 20))
    assert recorte is not None and int(recorte[0, 0, 0]) == 77


def test_a_closed_grabber_stops_capturing():
    grabber = _RoteiroDXGI([(duplication.NEW_FRAME, _quadro(90))])
    grabber.close()
    assert grabber.grab(Rect(0, 0, 20, 20)) is None


# ---------- a fachada e a queda para GDI ----------


class _GrabberFalso:
    def __init__(self, quadros):
        self.quadros = list(quadros)
        self.fechado = False
        self.pedidos = 0

    def grab(self, rect):
        self.pedidos += 1
        return self.quadros.pop(0) if self.quadros else None

    def close(self):
        self.fechado = True


def _fachada(dxgi=None, gdi=None):
    return ScreenGrabber(
        duplication_factory=(lambda: dxgi) if dxgi is not None else None,
        gdi_factory=(lambda: gdi) if gdi is not None else None,
    )


def test_duplication_is_the_primary_strategy():
    dxgi = _GrabberFalso([np.zeros((4, 4, 3), dtype=np.uint8)])
    gdi = _GrabberFalso([])
    fachada = _fachada(dxgi, gdi)
    assert fachada.grab(Rect(0, 0, 4, 4)) is not None
    assert fachada.strategy == "dxgi"
    assert gdi.pedidos == 0, "o GDI não deveria ter sido tocado"


def test_a_machine_without_duplication_falls_back_to_gdi():
    gdi = _GrabberFalso([np.zeros((4, 4, 3), dtype=np.uint8)])

    def sem_dxgi():
        raise DuplicationUnavailable("máquina virtual sem GPU")

    fachada = ScreenGrabber(duplication_factory=sem_dxgi, gdi_factory=lambda: gdi)
    assert fachada.grab(Rect(0, 0, 4, 4)) is not None
    assert fachada.strategy == "gdi"


def test_duplication_that_never_delivers_a_frame_gives_way_to_gdi():
    dxgi = _GrabberFalso([])  # devolve None para sempre
    gdi = _GrabberFalso([np.zeros((4, 4, 3), dtype=np.uint8)] * 50)
    fachada = _fachada(dxgi, gdi)

    for _ in range(DUPLICATION_TRIAL_GRABS - 1):
        assert fachada.grab(Rect(0, 0, 4, 4)) is None
        assert fachada.strategy == "dxgi"

    assert fachada.grab(Rect(0, 0, 4, 4)) is not None, "o GDI salva o quadro da desistência"
    assert fachada.strategy == "gdi"
    assert dxgi.fechado is True


def test_duplication_that_already_worked_is_never_abandoned():
    """Um quadro perdido depois de provado é transitório, não quebra.

    Alt-tab, tela de carregamento e troca de resolução produzem uma
    sequência de `None`; trocar de estratégia aí perderia a única que
    enxerga o jogo em tela cheia exclusiva.
    """
    dxgi = _GrabberFalso([np.zeros((4, 4, 3), dtype=np.uint8)])
    gdi = _GrabberFalso([])
    fachada = _fachada(dxgi, gdi)
    fachada.grab(Rect(0, 0, 4, 4))
    for _ in range(DUPLICATION_TRIAL_GRABS * 2):
        fachada.grab(Rect(0, 0, 4, 4))
    assert fachada.strategy == "dxgi"
    assert gdi.pedidos == 0


def test_an_empty_rectangle_is_refused_before_any_strategy_runs():
    dxgi = _GrabberFalso([])
    fachada = _fachada(dxgi, _GrabberFalso([]))
    assert fachada.grab(Rect(0, 0, 0, 10)) is None
    assert dxgi.pedidos == 0


def test_closing_the_facade_closes_both_strategies():
    dxgi = _GrabberFalso([])
    gdi = _GrabberFalso([])
    fachada = _fachada(dxgi, gdi)
    fachada._gdi = gdi  # força o GDI a existir sem esperar a desistência
    fachada.grab(Rect(0, 0, 4, 4))
    fachada.close()
    assert dxgi.fechado is True and gdi.fechado is True
    assert fachada.grab(Rect(0, 0, 4, 4)) is None


def test_an_unusable_duplication_is_closed_before_giving_way_to_gdi():
    """A falha precisa escapar da fábrica, senão o `grab` a engole.

    O `grab` do DXGI transforma toda exceção em `None` de propósito. Se
    a montagem do dispositivo acontecesse lá dentro, uma máquina sem GPU
    passaria os primeiros quatro segundos de toda partida capturando
    nada em vez de usar o GDI imediatamente.
    """
    fechados = []

    class _SemGPU:
        def prepare(self):
            raise DuplicationUnavailable("sem adaptador")

        def close(self):
            fechados.append(True)

    from lolqueue.vision import capture as capture_module

    monkey = _SemGPU()
    duplication.DuplicationGrabber, original = (lambda: monkey), duplication.DuplicationGrabber
    try:
        with pytest.raises(DuplicationUnavailable):
            capture_module._default_duplication()
    finally:
        duplication.DuplicationGrabber = original
    assert fechados == [True]


# ---------- o vigia deixa de ficar mudo ----------


class _VozFalsa:
    def __init__(self):
        self.ditas = []

    def prime(self, frases):
        pass

    def say(self, texto):
        self.ditas.append(texto)


class _Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def _vigia_cego(quadro):
    """Um `JungleWatcher` com partida em curso e captura inútil."""
    relogio = _Relogio()
    diario = []
    jogo = SimpleNamespace(
        side=1, enemy_jungler=SimpleNamespace(champion="Graves", summoner="x")
    )
    vigia = JungleWatcher(
        voice=_VozFalsa(),
        on_message=diario.append,
        viewport_fn=lambda: Rect(0, 0, 1920, 1080),
        locate_fn=lambda frame, area, flipped=False: None,
        grab_fn=lambda rect: quadro,
        game_fn=lambda: jogo,
        clock=relogio,
    )
    return vigia, relogio, diario


PRETO = np.zeros((100, 100, 3), dtype=np.uint8)


def cegueiras(diario):
    """Só as queixas de tela ilegível.

    O diário carrega o diagnóstico de cada etapa do laço — partida
    lida, minimapa achado, retrato ausente. Comparar o diário inteiro
    faria estes testes quebrarem toda vez que uma etapa nova aprendesse
    a se explicar, que é justamente o que se quer incentivar.
    """
    return [linha for linha in diario if linha == BLIND_MESSAGE]


def test_a_black_screen_is_reported_once_after_fifteen_seconds():
    vigia, relogio, diario = _vigia_cego(PRETO)
    vigia.tick()
    assert cegueiras(diario) == [], "não se avisa no primeiro quadro preto"

    relogio.agora = BLIND_SECONDS - 1.0
    vigia.tick()
    assert cegueiras(diario) == []

    relogio.agora = BLIND_SECONDS + 1.0
    vigia.tick()
    assert cegueiras(diario) == [BLIND_MESSAGE]


def test_the_black_screen_warning_never_repeats():
    vigia, relogio, diario = _vigia_cego(PRETO)
    vigia.tick()
    for passo in range(1, 40):
        relogio.agora = BLIND_SECONDS * passo
        vigia.tick()
    assert cegueiras(diario) == [BLIND_MESSAGE]


def test_the_warning_names_the_video_mode_to_change():
    assert "Sem bordas" in BLIND_MESSAGE


def test_a_missing_frame_counts_as_a_black_screen():
    vigia, relogio, diario = _vigia_cego(None)
    vigia.tick()
    relogio.agora = BLIND_SECONDS + 1.0
    vigia.tick()
    assert cegueiras(diario) == [BLIND_MESSAGE]


def test_a_usable_frame_resets_the_countdown():
    vigia, relogio, diario = _vigia_cego(PRETO)
    vigia.tick()

    relogio.agora = BLIND_SECONDS - 1.0
    vigia._grab = lambda rect: np.full((100, 100, 3), 40, dtype=np.uint8)
    vigia.tick()

    relogio.agora = BLIND_SECONDS + 1.0
    vigia._grab = lambda rect: PRETO
    vigia.tick()
    assert cegueiras(diario) == [], "a contagem recomeça quando a captura volta"


def test_resetting_arms_the_warning_again_for_the_next_game():
    vigia, relogio, diario = _vigia_cego(PRETO)
    vigia.tick()
    relogio.agora = BLIND_SECONDS + 1.0
    vigia.tick()
    assert cegueiras(diario) == [BLIND_MESSAGE]

    vigia.reset()
    relogio.agora = 100.0
    vigia.tick()
    relogio.agora = 100.0 + BLIND_SECONDS + 1.0
    vigia.tick()
    assert cegueiras(diario) == [BLIND_MESSAGE, BLIND_MESSAGE]


def test_no_blindness_is_reported_while_there_is_no_game_on_screen():
    """Sem partida não se captura nada, então não há cegueira a relatar.

    O laço continua tendo o que dizer — que ainda não achou a partida —,
    e é outro assunto: reclamar da tela preta antes de existir tela seria
    mandar o jogador mexer no vídeo por nada.
    """
    vigia, relogio, diario = _vigia_cego(PRETO)
    vigia._fetch = lambda: None
    for passo in range(10):
        relogio.agora = BLIND_SECONDS * passo
        vigia.tick()
    assert cegueiras(diario) == []


@pytest.mark.parametrize(
    "quadro, cego",
    [
        (None, True),
        (np.zeros((4, 4, 3), dtype=np.uint8), True),
        (np.zeros((0, 4, 3), dtype=np.uint8), True),
        (np.full((4, 4, 3), 1, dtype=np.uint8), False),
    ],
)
def test_only_a_truly_black_frame_counts_as_blind(quadro, cego):
    assert watcher_module._is_blank(quadro) is cego


# ---------------------------------------------------------------------------
# O modo de vídeo, dito antes de custar uma partida
# ---------------------------------------------------------------------------


def _vigia_parado(fullscreen, config=Path("game.cfg")):
    """Vigilância que liga e desliga na hora, sem tocar em tela nem em rede.

    `config` é o game.cfg que a vigilância diz ter encontrado. Vem
    preenchido de propósito: deixá-lo à descoberta real amarraria o
    teste à máquina que o roda — passaria em quem tem o League
    instalado e falharia em qualquer outra.
    """
    diario = []
    vigia = JungleWatcher(
        voice=_VozFalsa(),
        on_message=diario.append,
        viewport_fn=lambda: None,
        locate_fn=lambda frame, area, flipped=False: None,
        grab_fn=lambda rect: None,
        game_fn=lambda: None,
        fullscreen_fn=fullscreen,
        config_fn=lambda: config,
    )
    vigia.start()
    vigia.stop()
    return diario


def test_exclusive_fullscreen_is_announced_when_the_watch_starts():
    diario = _vigia_parado(lambda: True)
    assert FULLSCREEN_HINT in diario
    assert "Sem bordas" in FULLSCREEN_HINT


def test_borderless_says_nothing_about_video_mode():
    diario = _vigia_parado(lambda: False)
    assert all("Sem bordas" not in linha for linha in diario)


def test_a_game_cfg_that_was_not_found_is_said_out_loud():
    """A instalação em outro disco tem que aparecer, não sumir.

    Com o arquivo em lugar nenhum, `exclusive_fullscreen` responde
    "não" por falta de evidência — indistinguível de um "não" de
    verdade. Foi assim que um PC ficou mudo sem nenhuma pista: o
    aviso da tela cheia não saiu porque ninguém sabia o modo de vídeo.
    """
    diario = _vigia_parado(lambda: False, config=None)
    assert NOTE_NO_CONFIG in diario


def test_the_video_mode_is_not_guessed_when_there_is_no_file_to_read():
    """Sem arquivo, nem o alarme da tela cheia: seria chute."""
    diario = _vigia_parado(lambda: True, config=None)
    assert FULLSCREEN_HINT not in diario
    assert NOTE_NO_CONFIG in diario


def test_a_broken_config_read_does_not_take_the_watch_down():
    def explode():
        raise OSError("sem permissão")

    diario = _vigia_parado(explode)
    assert any("ligada" in linha for linha in diario)


@pytest.mark.parametrize(
    "linhas, exclusiva",
    [
        (["WindowMode=0"], True),
        (["WindowMode=1"], False),
        (["WindowMode=2"], False),
        (["FlipMiniMap=0"], False),
        (["WindowMode=cheio"], False),
        (["[General]", "Height=1440", "WindowMode=0", "Width=3440"], True),
    ],
)
def test_the_video_mode_is_read_from_the_game_config(tmp_path, linhas, exclusiva):
    cfg = tmp_path / "game.cfg"
    cfg.write_text(chr(10).join(linhas) + chr(10), encoding="utf-8")
    assert exclusive_fullscreen(cfg) is exclusiva


def test_a_config_that_does_not_exist_accuses_nothing(tmp_path):
    assert exclusive_fullscreen(tmp_path / "sumiu.cfg") is False


# ---------------------------------------------------------------------------
# O diário de bordo: cada etapa que emudece o aviso diz que emudeceu
# ---------------------------------------------------------------------------

LEGIVEL = np.full((100, 100, 3), 40, dtype=np.uint8)


def _vigia(**extra):
    """Vigilância com relógio na mão, voz de mentira e diário à parte."""
    relogio = _Relogio()
    diario = []
    voz = _VozFalsa()
    padrao = dict(
        voice=voz,
        on_message=diario.append,
        viewport_fn=lambda: Rect(0, 0, 1920, 1080),
        locate_fn=lambda frame, area, flipped=False: None,
        grab_fn=lambda rect: LEGIVEL,
        game_fn=lambda: None,
        clock=relogio,
        fullscreen_fn=lambda: False,
    )
    padrao.update(extra)
    return JungleWatcher(**padrao), relogio, diario, voz


def _rodar(vigia, relogio, vezes, passo=GAME_RETRY_SECONDS):
    for indice in range(vezes):
        relogio.agora = passo * (indice + 1)
        vigia.tick()


def test_a_match_that_never_appears_is_reported_once():
    """Sem partida o laço é mudo por projeto — e mudo demais para depurar."""
    vigia, relogio, diario, _voz = _vigia()

    _rodar(vigia, relogio, GAME_TRIES_BEFORE_WARNING + 4)

    assert diario.count(NOTE_NO_GAME) == 1


def test_the_first_seconds_without_a_match_say_nothing():
    """A tela de carregamento é longa; reclamar dela seria alarme falso."""
    vigia, relogio, diario, _voz = _vigia()

    _rodar(vigia, relogio, GAME_TRIES_BEFORE_WARNING - 1)

    assert diario == []


def test_a_match_without_a_readable_enemy_jungler_is_reported():
    """Dois Punir do outro lado, ou fila sem rotas: ninguém para vigiar."""
    jogo = SimpleNamespace(side=1, enemy_jungler=None, lane_name="rota do meio")
    vigia, relogio, diario, _voz = _vigia(game_fn=lambda: jogo)

    _rodar(vigia, relogio, JUNGLER_REREADS + 3, passo=GAME_RETRY_SECONDS + 1.0)

    assert diario.count(NOTE_NO_JUNGLER) == 1


def test_the_jungler_is_not_given_up_on_at_the_first_reading():
    """A lista chega incompleta na tela de carregamento; não é sentença."""
    jogo = SimpleNamespace(side=1, enemy_jungler=None, lane_name="rota do meio")
    vigia, relogio, diario, _voz = _vigia(game_fn=lambda: jogo)

    _rodar(vigia, relogio, JUNGLER_REREADS, passo=GAME_RETRY_SECONDS + 1.0)

    assert NOTE_NO_JUNGLER not in diario


def test_a_jungler_that_only_appears_on_the_second_reading_is_used():
    """O bug que emudecia a partida inteira: primeira leitura sem feitiços.

    A porta 2999 responde antes de a partida existir de verdade, e a
    resposta de então vinha sem `summonerSpells` e sem `position`. Como
    a leitura era guardada para sempre, o jungler inimigo ficava
    desconhecido do primeiro ao último minuto.
    """
    graves = SimpleNamespace(champion="Graves", summoner="x")
    leituras = [
        SimpleNamespace(side=1, enemy_jungler=None, lane_name="rota do meio"),
        SimpleNamespace(side=1, enemy_jungler=graves, lane_name="rota do meio"),
    ]
    vigia, relogio, diario, _voz = _vigia(game_fn=lambda: leituras.pop(0))

    _rodar(vigia, relogio, 2, passo=GAME_RETRY_SECONDS + 1.0)

    assert vigia._game.enemy_jungler is graves
    assert NOTE_NO_JUNGLER not in diario
    # Achado o jungler, a lista para de ser relida: a composição não
    # muda no meio do jogo e a porta 2999 não precisa apanhar à toa.
    _rodar(vigia, relogio, 4, passo=GAME_RETRY_SECONDS + 1.0)
    assert leituras == []


def test_a_lost_reading_does_not_erase_the_match_already_read():
    """A porta 2999 pisca em qualquer reconexão; a partida continua a mesma."""
    jogo = SimpleNamespace(side=1, enemy_jungler=None, lane_name="rota do meio")
    respostas = [jogo, None, jogo]

    def ler():
        if not respostas:
            return jogo
        resposta = respostas.pop(0)
        if resposta is None:
            raise RuntimeError("porta fechada")
        return resposta

    vigia, relogio, _diario, _voz = _vigia(game_fn=ler)

    _rodar(vigia, relogio, 2, passo=GAME_RETRY_SECONDS + 1.0)

    assert vigia._game is jogo


def test_a_minimap_that_is_not_found_is_reported():
    jogo = SimpleNamespace(
        side=1, enemy_jungler=SimpleNamespace(champion="Graves", summoner="x")
    )
    vigia, relogio, diario, _voz = _vigia(game_fn=lambda: jogo)

    _rodar(vigia, relogio, 4, passo=RELOCATE_SECONDS + 1.0)

    assert diario.count(NOTE_NO_MINIMAP) == 1


def test_a_black_screen_is_not_blamed_on_the_minimap():
    """Um diagnóstico por causa: tela ilegível já tem o seu próprio aviso."""
    vigia, relogio, diario = _vigia_cego(PRETO)

    for passo in range(5):
        relogio.agora = (RELOCATE_SECONDS + 1.0) * passo
        vigia.tick()

    assert NOTE_NO_MINIMAP not in diario


def test_the_watch_says_which_side_and_lane_it_read():
    """A prova de que a partida foi lida — e de que rota o aviso vai usar."""
    jogo = SimpleNamespace(
        side=-1,
        lane_name="rota de baixo",
        enemy_jungler=SimpleNamespace(champion="Graves", summoner="x"),
    )
    vigia, relogio, diario, _voz = _vigia(game_fn=lambda: jogo)

    vigia.tick()
    vigia.tick()

    lidas = [linha for linha in diario if linha.startswith("Partida lida")]
    assert lidas == ["Partida lida: você é rota de baixo do lado vermelho."]


# ---------------------------------------------------------------------------
# O silêncio explicado em voz alta
# ---------------------------------------------------------------------------


def test_exclusive_fullscreen_is_also_spoken():
    """O jogador está dentro da partida: o arquivo de registro não o alcança."""
    vigia, _relogio, _diario, voz = _vigia(fullscreen_fn=lambda: True)

    vigia.start()
    vigia.stop()

    assert voz.ditas == [FULLSCREEN_SPOKEN]


def test_borderless_is_not_spoken():
    vigia, _relogio, _diario, voz = _vigia(fullscreen_fn=lambda: False)

    vigia.start()
    vigia.stop()

    assert voz.ditas == []


def test_a_blind_capture_is_also_spoken_once():
    jogo = SimpleNamespace(
        side=1, enemy_jungler=SimpleNamespace(champion="Graves", summoner="x")
    )
    vigia, relogio, _diario, voz = _vigia(game_fn=lambda: jogo, grab_fn=lambda rect: PRETO)

    vigia.tick()
    for passo in range(1, 10):
        relogio.agora = BLIND_SECONDS * passo
        vigia.tick()

    assert voz.ditas == [BLIND_SPOKEN]


def test_a_voice_that_fails_does_not_take_the_watch_down():
    class VozQuebrada:
        def prime(self, frases):
            raise RuntimeError("sem áudio")

        def say(self, texto):
            raise RuntimeError("sem áudio")

    vigia, _relogio, diario, _voz = _vigia(
        voice=VozQuebrada(), fullscreen_fn=lambda: True
    )

    vigia.start()
    vigia.stop()

    assert FULLSCREEN_HINT in diario
