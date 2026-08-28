"""O laço que vigia o minimapa e fala quando o jungler inimigo aparece.

Junta as peças que já existiam soltas: acha a janela do jogo, localiza o
minimapa dentro dela, recorta só esse pedaço a cada quadro, procura o
retrato do jungler inimigo e manda a frase pronta para a voz.

Roda numa thread própria porque tudo aqui é espera — captura de tela,
requisição ao jogo, síntese — e nada disso pode segurar a interface.
Nenhuma exceção sobe daqui: um erro de captura no meio da partida não
pode derrubar o app inteiro, só custar um quadro.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from . import gamecfg
from . import minimap as minimap_module
from . import window as window_module
from .callout import REPEAT_SECONDS, Callout, all_phrases, announce
from .detect import Detector
from .icons import ChampionIcons
from .livegame import LiveGame, LiveGameUnavailable
from .livegame import fetch as fetch_game

#: Quantos quadros por segundo o laço tenta manter. O jungler leva pelo
#: menos um segundo cruzando o minimapa; cinco quadros bastam para pegá-lo
#: e deixam a CPU quase livre.
FRAMES_PER_SECOND = 5.0

#: De quanto em quanto tempo o minimapa é reprocurado. Ele não anda, mas
#: a janela do jogo pode mudar de tamanho ou de monitor no meio da partida.
RELOCATE_SECONDS = 20.0

#: De quanto em quanto tempo a partida é reconsultada enquanto não há uma.
GAME_RETRY_SECONDS = 10.0

#: Quanto o laço dorme quando não há partida nenhuma na tela.
IDLE_SECONDS = 2.0

#: Lado do retrato do jungler como fração do lado do minimapa. As escalas
#: ao redor cobrem as resoluções em que o arredondamento cai um pixel para
#: fora, e o zoom que o jogador pode dar no próprio minimapa.
ICON_FRACTION = 0.075
ICON_SCALES = (0.85, 1.0, 1.18)

#: Piso entre dois avisos de zonas diferentes. Sem ele, o ícone piscando
#: na fronteira de duas zonas viraria tagarelice em cima do jogador.
MIN_GAP_SECONDS = 2.5

#: Quanto tempo de captura inútil seguida antes de avisar o usuário. É
#: generoso de propósito: tela de carregamento, alt-tab e a transição
#: para a partida produzem quadros pretos legítimos por alguns segundos,
#: e um alarme falso aqui é pior que um aviso atrasado.
BLIND_SECONDS = 15.0

#: O aviso que faltava. O usuário jogou várias partidas achando que a
#: vigilância estava quebrada porque ela ficava simplesmente muda: a
#: captura vinha preta em fullscreen exclusivo e nada dizia isso a
#: ninguém. Sai uma vez por partida, nunca em laço.
BLIND_MESSAGE = (
    "Não consegui ler a tela do jogo: a captura está vindo toda preta. "
    "Isso costuma ser o modo de vídeo em tela cheia exclusiva. "
    'Em Opções > Vídeo, troque o Modo de Vídeo para "Sem bordas" e o '
    "aviso do jungler volta a funcionar."
)

#: O mesmo recado, dito antes de custar uma partida. O game.cfg diz o
#: modo de vídeo sem precisar de um único quadro, então quando ele já
#: acusa tela cheia exclusiva não há motivo para esperar quinze segundos
#: de silêncio para explicar o silêncio. Sai uma vez, ao ligar.
FULLSCREEN_HINT = (
    "Atenção: o jogo está em tela cheia exclusiva, e nesse modo a captura "
    "da tela costuma vir preta — o aviso do jungler fica mudo. "
    'Em Opções > Vídeo, troque o Modo de Vídeo para "Sem bordas".'
)

#: As mesmas duas notícias, ditas em voz alta. O registro em arquivo não
#: chega a quem está dentro da partida — e o jogador que não escuta nada
#: conclui que o app está quebrado, não que está cego. Curtas de
#: propósito: uma frase, uma vez, e nunca durante uma luta.
FULLSCREEN_SPOKEN = (
    "Aviso do jungler indisponível: o jogo está em tela cheia exclusiva. "
    "Troque o modo de vídeo para sem bordas."
)
BLIND_SPOKEN = (
    "Não consigo ler a tela do jogo. Troque o modo de vídeo para sem bordas."
)

#: Quantas consultas sem partida antes de dizer que ainda não achei uma.
#: Vezes `GAME_RETRY_SECONDS` dá um minuto, que é mais que a tela de
#: carregamento mais lenta — abaixo disso o aviso sairia toda partida.
GAME_TRIES_BEFORE_WARNING = 6

#: O diário de bordo da vigilância. Cada etapa que pode emudecer o aviso
#: diz, uma vez por partida, que emudeceu — e por quê. Sem isto o laço
#: falha exatamente igual em cinco lugares diferentes: em silêncio.
NOTE_NO_GAME = (
    "Ainda não achei a partida ao vivo (porta 2999) — o aviso do jungler "
    "fica esperando."
)
NOTE_NO_JUNGLER = (
    "Partida encontrada, mas não dá para dizer quem é o jungler inimigo — "
    "sem aviso nesta partida."
)
NOTE_NO_MINIMAP = (
    "Não localizei o minimapa na tela; sigo procurando a cada "
    f"{int(RELOCATE_SECONDS)} segundos."
)


def _is_blank(frame) -> bool:
    """Verdadeiro para o quadro que não dá para usar: nulo ou todo preto.

    Preto absoluto não é uma cena escura — é a assinatura da captura
    falhando. Nem a névoa de guerra do minimapa chega a zero em todos os
    canais de todos os pixels.
    """
    if frame is None:
        return True
    try:
        return frame.size == 0 or int(frame.max()) == 0
    except Exception:  # pragma: no cover - rede de segurança
        return True


class JungleWatcher:
    """Vigia o minimapa durante a partida e fala os avisos.

    Todos os colaboradores entram pelo construtor: é o que permite testar
    o laço inteiro com quadros sintéticos, sem abrir o jogo nem tocar som.
    """

    def __init__(
        self,
        voice,
        icons: ChampionIcons | None = None,
        on_message: Callable[[str], None] | None = None,
        viewport_fn=None,
        locate_fn=None,
        grab_fn=None,
        game_fn=None,
        clock: Callable[[], float] = time.monotonic,
        fullscreen_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._voice = voice
        self._icons = icons if icons is not None else ChampionIcons()
        self._on_message = on_message
        self._viewport = viewport_fn or window_module.viewport
        self._locate = locate_fn or minimap_module.locate
        self._grab = grab_fn or self._screen_grab
        self._fetch = game_fn or fetch_game
        self._clock = clock
        self._fullscreen = fullscreen_fn or gamecfg.exclusive_fullscreen

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._grabber = None

        self._game: LiveGame | None = None
        self._game_at = 0.0
        self._champion = ""
        self._primed = ""
        self._detector: Detector | None = None
        self._minimap = None
        self._minimap_at = 0.0
        self._said: dict[str, float] = {}
        self._last_said = 0.0
        self._blind_since: float | None = None
        self._blind_warned = False
        self._notes: set[str] = set()
        self._game_tries = 0

    # ---------- ciclo de vida ----------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Liga a vigilância. Chamar duas vezes não abre duas threads."""
        if self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lolqueue-selva", daemon=True
        )
        self._thread.start()
        self._log("Vigilância do jungler inimigo ligada.")
        self._warn_fullscreen()
        return True

    def _warn_fullscreen(self) -> None:
        """Avisa do modo de vídeo cego antes que ele custe uma partida.

        Ler um arquivo de texto não pode derrubar a vigilância que acabou
        de subir, então qualquer tropeço aqui é engolido: o aviso dos
        quinze segundos continua de guarda.
        """
        try:
            if self._fullscreen():
                self._log(FULLSCREEN_HINT)
                self._speak(FULLSCREEN_SPOKEN)
        except Exception:  # pragma: no cover - rede de segurança
            pass

    def stop(self) -> None:
        """Desliga e espera a thread sair, para não capturar tela depois."""
        thread = self._thread
        self._stop.set()
        self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)
            self._log("Vigilância do jungler inimigo desligada.")
        self._release()
        self.reset()

    def reset(self) -> None:
        """Esquece a partida anterior, sem desligar o laço."""
        self._game = None
        self._game_at = 0.0
        self._champion = ""
        self._primed = ""
        self._detector = None
        self._minimap = None
        self._minimap_at = 0.0
        self._said.clear()
        self._last_said = 0.0
        self._blind_since = None
        self._blind_warned = False
        self._notes.clear()
        self._game_tries = 0

    # ---------- o laço ----------

    def _run(self) -> None:
        while not self._stop.is_set():
            inicio = self._clock()
            try:
                self.tick()
            except Exception:
                # Um quadro perdido é barato; a thread morta faria o app
                # ficar mudo pelo resto da partida sem ninguém perceber.
                pass
            espera = self._pause() - (self._clock() - inicio)
            self._stop.wait(max(espera, 0.0))
        self._release()

    def _pause(self) -> float:
        if self._game is None:
            return IDLE_SECONDS
        return 1.0 / FRAMES_PER_SECOND

    def tick(self) -> Callout | None:
        """Um quadro: capta, procura, e fala se houver o que falar."""
        agora = self._clock()
        jogo = self._ensure_game(agora)
        if jogo is None:
            return None
        jungler = jogo.enemy_jungler
        if jungler is None:
            self._note("sem_jungler", NOTE_NO_JUNGLER)
            return None
        self._prime(jogo, jungler.champion)

        mapa = self._ensure_minimap(agora)
        if mapa is None:
            return None
        quadro = self._capture(mapa.rect, agora)
        if quadro is None:
            # O recorte parou de valer: janela minimizada ou redimensionada.
            self._minimap = None
            return None

        detector = self._ensure_detector(jungler.champion, mapa)
        if detector is None:
            return None
        achado = detector.feed(quadro)
        if achado is None:
            return None

        mx, my = mapa.to_map(achado.x, achado.y)
        aviso = announce(jungler.champion, mx, my, jogo)
        if not self._due(aviso, agora):
            return None
        self._said[aviso.zone_key] = agora
        self._last_said = agora
        self._voice.say(aviso.text)
        self._log(aviso.text)
        return aviso

    # ---------- as peças ----------

    def _ensure_game(self, agora: float) -> LiveGame | None:
        if self._game is not None:
            return self._game
        if self._game_at and agora - self._game_at < GAME_RETRY_SECONDS:
            return None
        self._game_at = agora
        self._game_tries += 1
        try:
            self._game = self._fetch()
        except (LiveGameUnavailable, Exception):
            self._game = None
        if self._game is None:
            if self._game_tries >= GAME_TRIES_BEFORE_WARNING:
                self._note("sem_partida", NOTE_NO_GAME)
            return None
        rota = getattr(self._game, "lane_name", "") or "rota desconhecida"
        lado = "azul" if getattr(self._game, "side", 1) > 0 else "vermelho"
        self._note("partida", f"Partida lida: você é {rota} do lado {lado}.")
        return self._game

    def _prime(self, jogo: LiveGame, champion: str) -> None:
        """Sintetiza tudo o que pode ser dito, antes de precisar dizer.

        A voz neural leva centenas de milissegundos por frase: pedi-la na
        hora do gank entregaria o aviso depois do abate.
        """
        if not champion or self._primed == champion:
            return
        self._primed = champion
        try:
            self._voice.prime(all_phrases(champion, jogo.side))
        except Exception:
            pass

    def _ensure_minimap(self, agora: float):
        if self._minimap is not None and agora - self._minimap_at < RELOCATE_SECONDS:
            return self._minimap
        vista = self._viewport()
        if vista is not None:
            area = minimap_module.search_area(vista)
            quadro = self._capture(area, agora)
            if _is_blank(quadro):
                # Tela ilegível não é minimapa ausente: quem explica o
                # silêncio nesse caso é o aviso de captura preta, e
                # dizer as duas coisas só confundiria quem lê o diário.
                self._minimap_at = agora
                return self._minimap
            if quadro is not None:
                # De propósito sem `flipped`: quem desvira é `to_world`,
                # com o lado do jogador em mãos. Virar aqui também giraria
                # o ponto duas vezes e mandaria o aviso para o lado errado.
                achado = self._locate(quadro, area)
                if achado is not None:
                    if self._minimap is None or achado.rect != self._minimap.rect:
                        # Molde montado para outro tamanho de minimapa não
                        # casa com nada; melhor recomeçar do que cegar.
                        self._detector = None
                    self._minimap = achado
                    self._note(
                        "minimapa",
                        f"Minimapa localizado: {achado.rect.width} por "
                        f"{achado.rect.height} pixels.",
                    )
                else:
                    self._note("sem_minimapa", NOTE_NO_MINIMAP)
        self._minimap_at = agora
        return self._minimap

    def _ensure_detector(self, champion: str, mapa) -> Detector | None:
        if self._detector is not None and self._champion == champion:
            return self._detector
        lado = max(int(round(mapa.rect.width * ICON_FRACTION)), 1)
        moldes = []
        for escala in ICON_SCALES:
            molde = self._icons.template(champion, max(int(round(lado * escala)), 1))
            if molde is not None:
                moldes.append(molde)
        if not moldes:
            self._note(
                "sem_retrato",
                f"Não tenho o retrato de {champion} para procurar no minimapa.",
            )
            return None
        self._champion = champion
        self._detector = Detector(moldes)
        return self._detector

    def _due(self, aviso: Callout, agora: float) -> bool:
        anterior = self._said.get(aviso.zone_key)
        if anterior is not None and agora - anterior < REPEAT_SECONDS:
            return False
        if self._last_said and agora - self._last_said < MIN_GAP_SECONDS:
            return False
        return True

    # ---------- captura ----------

    def _capture(self, rect, agora: float):
        """Captura e, de quebra, percebe quando a tela está ilegível.

        O quadro segue para quem pediu do jeito que veio — inclusive
        preto, porque `locate` e `Detector` já sabem não achar nada
        nele. O que muda é que a cegueira deixa de ser silenciosa.
        """
        quadro = self._grab(rect)
        if not _is_blank(quadro):
            self._blind_since = None
            return quadro
        if self._blind_since is None:
            self._blind_since = agora
        elif not self._blind_warned and agora - self._blind_since >= BLIND_SECONDS:
            # Uma vez só: repetir a cada quadro encheria o diário e
            # esconderia tudo o mais que aconteceu na partida.
            self._blind_warned = True
            self._log(BLIND_MESSAGE)
            self._speak(BLIND_SPOKEN)
        return quadro

    def _screen_grab(self, rect):
        from .capture import ScreenGrabber

        if self._grabber is None:
            # Um grabber por thread: criar na thread que usa é o que o
            # próprio módulo de captura pede, tanto no DXGI quanto no GDI.
            self._grabber = ScreenGrabber()
        return self._grabber.grab(rect)

    def _release(self) -> None:
        grabber = self._grabber
        self._grabber = None
        if grabber is not None:
            try:
                grabber.close()
            except Exception:
                pass

    def _note(self, key: str, message: str) -> None:
        """Uma etapa do laço se explicando — uma vez por partida.

        `reset` esvazia as notas junto com o resto, então cada partida
        recomeça o diário do zero. Repetir a cada quadro encheria o
        arquivo e esconderia tudo o que aconteceu na partida.
        """
        if key in self._notes:
            return
        self._notes.add(key)
        self._log(message)

    def _speak(self, text: str) -> None:
        """Fala sem deixar a voz derrubar o laço que a chamou."""
        try:
            self._voice.say(text)
        except Exception:  # pragma: no cover - rede de segurança
            pass

    def _log(self, message: str) -> None:
        if self._on_message is None:
            return
        try:
            self._on_message(message)
        except Exception:
            pass
