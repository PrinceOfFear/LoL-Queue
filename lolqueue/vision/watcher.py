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

#: De quanto em quanto tempo o minimapa é procurado enquanto ele ainda
#: não foi achado. Antes a busca acontecia a cada quadro, cinco vezes por
#: segundo, e a partida começa justamente com dezenas de segundos de tela
#: de carregamento em que não há minimapa nenhum para achar: era meia
#: tela recortada e medida em vão, sem pressa nenhuma que justificasse.
#: Um segundo continua imperceptível para quem espera.
SEARCH_SECONDS = 1.0

#: De quanto em quanto tempo a partida é reconsultada enquanto não há uma.
GAME_RETRY_SECONDS = 10.0

#: Quantas releituras da lista de jogadores antes de aceitar que o
#: jungler inimigo é mesmo indecifrável. A porta 2999 já responde na tela
#: de carregamento, mas nem sempre com os feitiços e as rotas
#: preenchidos, e a primeira resposta ficava valendo para sempre: uma
#: leitura incompleta condenava a partida inteira ao silêncio. Vezes
#: `GAME_RETRY_SECONDS` dá um minuto de paciência, que cobre a tela de
#: carregamento mais lenta.
JUNGLER_REREADS = 6

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

#: A mesma tela preta, quando o game.cfg já disse que o modo de vídeo
#: não é o culpado. Mandar trocar uma opção que já está certa é pior do
#: que não dizer nada: o jogador mexe no vídeo, nada muda, e ele conclui
#: que o aviso é quebrado — quando a pista verdadeira estava em outro
#: lugar o tempo todo.
BLIND_MODE_IS_FINE = (
    "Não consegui ler a tela do jogo: a captura está vindo toda preta. "
    "O modo de vídeo não é o problema — conferi no game.cfg e ele não "
    "está em tela cheia exclusiva. Nesses casos a causa costuma ser o "
    "HDR do Windows ligado, um overlay por cima do jogo (Discord, "
    "GeForce Experience) ou o jogo rodando numa placa de vídeo "
    "diferente da que o app captura."
)

#: A captura antiga entrou em cena. Ela é lenta e, por cima de um jogo
#: em tela cheia, costuma devolver preto — ou seja, é a explicação mais
#: provável de um silêncio que ainda vai acontecer. Sem esta linha, a
#: degradação era definitiva e invisível: o app trocava de estratégia
#: para sempre e ninguém ficava sabendo.
#: O único caso em que não achar o game.cfg deixa de ser um detalhe e
#: passa a ser risco de aviso errado. Do lado azul, a opção "Girar
#: Minimapa" não muda nada; do vermelho com ela ligada, o mapa inteiro
#: vira de cabeça para baixo — e um aviso que ignore isso manda o
#: jogador para o canto oposto do mapa, soando como acerto. Por isso
#: este é falado, e não só escrito: quem está em partida não lê diário.
FLIP_RISK_NOTE = (
    "Você está do lado vermelho e não achei o game.cfg desta máquina. "
    "Se a opção Girar Minimapa estiver ligada nas suas configurações, "
    "os avisos de lugar podem sair invertidos — desligue a opção ou "
    "confira o lado antes de reagir."
)

FLIP_RISK_SPOKEN = (
    "Atenção: não sei se seu minimapa está girado. Os avisos de lugar "
    "podem sair invertidos."
)

#: Os dois times com o mesmo campeão na selva. O retrato é idêntico e o
#: anel do time fica de fora da comparação, então o aliado dispara o
#: aviso do inimigo. Só acontece fora de ranqueada e draft.
NOTE_TWIN_JUNGLER = (
    "Os dois times têm {champion} na selva. Como leio o minimapa pelo "
    "retrato do campeão, não consigo separar um do outro: alguns avisos "
    "podem ser o seu jungler, não o inimigo."
)

NOTE_GDI = (
    "A captura rápida (DXGI) não funcionou nesta máquina e caí para o "
    "método antigo (GDI), que é mais lento e costuma vir preto por cima "
    "do jogo. Se o aviso do jungler ficar mudo nesta partida, começe a "
    "investigação por aqui."
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
    "Ainda não localizei o minimapa na tela; sigo procurando a cada "
    f"{SEARCH_SECONDS:.0f} segundo. É o esperado na tela de carregamento, "
    "onde não há minimapa nenhum para achar."
)

#: A janela da partida não é a mesma coisa que a tela preta. Sem janela
#: não há nem o que capturar, então nem o aviso de captura preta sai: o
#: diário mostrava a partida lida e depois nada, para sempre. Acontece
#: com a janela minimizada, com o jogo num monitor que sumiu e com
#: resolução abaixo do mínimo que a busca do minimapa aceita.
NOTE_NO_WINDOW = (
    "Não encontrei a janela da partida na tela — sem ela não tenho o que "
    "capturar. Se o jogo está minimizado, restaure-o; o aviso volta "
    "sozinho quando a janela reaparecer."
)

#: Quantas voltas seguidas do laço podem falhar antes de o problema
#: virar notícia. Uma exceção solta é um quadro perdido e não interessa
#: a ninguém; a mesma exceção repetida é a partida inteira muda, que é
#: exatamente o que esta vigilância existe para não deixar acontecer.
FAILURES_BEFORE_WARNING = 5
#: O game.cfg responde duas perguntas que mudam o aviso: se a captura
#: vem preta e se o minimapa está girado. Não achar o arquivo não
#: impede a vigilância de rodar, mas apaga os dois diagnósticos — e um
#: app que erra o canto do mapa sem nunca dizer por quê é pior que um
#: app calado. Isto existe para que a instalação em outro disco apareça
#: no diário em vez de virar mistério.
NOTE_NO_CONFIG = (
    "Não encontrei o game.cfg do League nesta máquina. O aviso continua "
    "funcionando, mas não consigo checar o modo de vídeo nem se o "
    "minimapa está girado (opção Girar Minimapa)."
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
        config_fn=None,
    ) -> None:
        self._voice = voice
        self._icons = icons if icons is not None else ChampionIcons()
        self._on_message = on_message
        self._viewport = viewport_fn or window_module.viewport
        self._locate = locate_fn or minimap_module.locate
        self._grab = grab_fn or self._screen_grab
        self._fetch = game_fn or self._fetch_live
        self._clock = clock
        self._fullscreen = fullscreen_fn or gamecfg.exclusive_fullscreen
        self._config_path = config_fn or gamecfg.config_path

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._grabber = None

        self._game: LiveGame | None = None
        self._game_at = 0.0
        self._falhas = 0
        self._rereads = 0
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
            if self._config_path() is None:
                # Sem o arquivo não há o que checar, e afirmar "está tudo
                # certo" seria mentir: o silêncio aqui é o mesmo de uma
                # tela cheia exclusiva não detectada.
                self._note("sem_config", NOTE_NO_CONFIG)
            elif self._fullscreen():
                self._log(FULLSCREEN_HINT)
                self._speak(FULLSCREEN_SPOKEN)
        except Exception:  # pragma: no cover - rede de segurança
            pass

    def stop(self) -> None:
        """Desliga e espera a thread sair, para não capturar tela depois.

        Quem solta os recursos de captura é o próprio laço, no fim do
        `_run`. Aqui só se solta o que sobrou de uma vigilância que nunca
        chegou a ter thread — o caso de quem chamou `tick()` na mão.

        A diferença não é preciosismo: o `ScreenGrabber` guarda objetos
        COM do DXGI presos à thread que os criou, e fechá-los daqui, com
        `lolqueue-selva` ainda dentro de um `grab`, derruba o processo
        inteiro — o app fecharia com um estouro em vez de fechar. Havia
        ainda um segundo estrago mais silencioso: zerar `_grabber` no
        meio de um quadro fazia o `tick` em curso criar outro logo em
        seguida, e a tela continuava sendo capturada depois da linha
        "Vigilância desligada" no diário.

        O `join` com prazo é o que mantém a promessa do nome: se o laço
        não sair em três segundos, a thread é daemon e o processo morre
        com ela mesmo assim.
        """
        thread = self._thread
        self._stop.set()
        self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)
            self._log("Vigilância do jungler inimigo desligada.")
        if thread is None or not thread.is_alive():
            self._release()
        self.reset()

    def reset(self) -> None:
        """Esquece a partida anterior, sem desligar o laço."""
        self._game = None
        self._game_at = 0.0
        self._falhas = 0
        self._rereads = 0
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
            except Exception as erro:
                # Um quadro perdido é barato; a thread morta faria o app
                # ficar mudo pelo resto da partida sem ninguém perceber.
                # Mas engolir sempre e calado é o mesmo defeito por outro
                # caminho: uma exceção que se repete a cada quadro é a
                # partida inteira sem aviso, e antes disto não sobrava
                # rastro nenhum de que algo tinha quebrado.
                self._falhas += 1
                if self._falhas >= FAILURES_BEFORE_WARNING:
                    self._note(
                        "laco_falhando",
                        "O aviso do jungler está falhando a cada quadro "
                        f"({type(erro).__name__}: {erro}). Ele não vai sair "
                        "nesta partida.",
                    )
                    self._speak("Aviso do jungler indisponível nesta partida.")
            else:
                self._falhas = 0
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
            # Só reclama depois de esgotada a paciência: anotar que a
            # partida não tem jungler enquanto a lista de jogadores
            # ainda está chegando é registrar um diagnóstico que a
            # leitura seguinte desmente.
            if self._rereads >= JUNGLER_REREADS:
                self._note("sem_jungler", NOTE_NO_JUNGLER)
            return None
        if getattr(jogo, "jungler_has_a_twin", False):
            self._note(
                "jungler_sosia",
                NOTE_TWIN_JUNGLER.format(champion=jungler.champion),
            )
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
        self._speak(aviso.text)
        self._log(aviso.text)
        return aviso

    # ---------- as peças ----------

    def _ensure_game(self, agora: float) -> LiveGame | None:
        if not self._stale_game():
            return self._game
        if self._game_at and agora - self._game_at < GAME_RETRY_SECONDS:
            return self._game
        self._game_at = agora
        if self._game is None:
            self._game_tries += 1
        else:
            self._rereads += 1
        try:
            lida = self._fetch()
        except LiveGameUnavailable:
            lida = None
        except Exception as erro:
            # Porta 2999 fechada é rotina e já tem recado próprio. Outra
            # coisa qualquer aqui é defeito, e some junto com a rotina se
            # as duas caírem no mesmo `except`: o diário culpava a porta
            # em todo caso, mandando quem investigasse para o lado errado.
            lida = None
            self._note(
                "erro_partida",
                "Erro inesperado ao ler a partida ao vivo "
                f"({type(erro).__name__}); tratando como partida ausente.",
            )
        if lida is None:
            # Perder uma releitura não apaga a partida que já foi lida:
            # o jogo fecha a porta 2999 por um instante em qualquer
            # reconexão, e esquecer tudo ali dentro custaria o resto da
            # partida em silêncio.
            if self._game is None and self._game_tries >= GAME_TRIES_BEFORE_WARNING:
                self._note("sem_partida", NOTE_NO_GAME)
            return self._game
        primeira = self._game is None
        self._game = lida
        if primeira:
            rota = getattr(lida, "lane_name", "") or "rota desconhecida"
            vermelho = getattr(lida, "side", 1) < 0
            lado = "vermelho" if vermelho else "azul"
            self._note("partida", f"Partida lida: você é {rota} do lado {lado}.")
            self._warn_flip_risk(vermelho)
        return self._game

    def _warn_flip_risk(self, vermelho: bool) -> None:
        """Avisa quando o aviso em si pode estar espelhado.

        Só o lado vermelho corre esse risco, e só quando o game.cfg não
        foi encontrado: sem o arquivo, `flip_minimap` devolve o padrão do
        jogo, e quem ligou a opção recebe cada lugar trocado pelo oposto.
        Errar o canto do mapa é pior que não avisar nada, então este é
        dito em voz alta — a nota de "não achei o game.cfg" que já
        existia ficava só no diário, que ninguém lê no meio da partida.
        """
        if not vermelho:
            return
        try:
            if self._config_path() is not None:
                return
        except Exception:  # pragma: no cover - rede de segurança
            pass
        self._note("risco_espelho", FLIP_RISK_NOTE)
        self._speak(FLIP_RISK_SPOKEN)

    def _stale_game(self) -> bool:
        """Se ainda vale a pena perguntar de novo quem está nesta partida.

        A lista de jogadores da porta 2999 já responde na tela de
        carregamento, mas às vezes sem os feitiços e sem as rotas — e a
        primeira resposta era guardada para sempre. Bastava calhar de a
        primeira leitura chegar incompleta para o jungler inimigo ficar
        desconhecido a partida inteira, que é exatamente o silêncio que
        o jogador levou para casa achando que o app estava quebrado.

        Achado o jungler, ou esgotada a paciência, a leitura vira
        definitiva: a composição não muda no meio do jogo, e insistir
        seria bater na porta do jogo por nada até o Nexus cair.
        """
        if self._game is None:
            return True
        if self._rereads >= JUNGLER_REREADS:
            return False
        return getattr(self._game, "enemy_jungler", None) is None

    def _fetch_live(self) -> LiveGame:
        """A partida lida do jogo, com a opção de girar o minimapa junto.

        `fetch` aceita `flip_minimap` desde sempre e ninguém preenchia:
        o laço chamava `fetch()` seco, e toda partida saía como se o
        minimapa nunca girasse. Para quem joga de vermelho com
        `FlipMiniMap` ligado, isso espelha o aviso e manda o jogador
        para o canto oposto do mapa — o erro mais caro que este app
        consegue cometer, porque soa exatamente como um acerto.
        """
        return fetch_game(flip_minimap=gamecfg.flip_minimap())

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
        espera = RELOCATE_SECONDS if self._minimap is not None else SEARCH_SECONDS
        if self._minimap_at and agora - self._minimap_at < espera:
            return self._minimap
        vista = self._viewport()
        if vista is None:
            self._note("sem_janela", NOTE_NO_WINDOW)
        else:
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
            self._log(self._blind_message())
            self._speak(BLIND_SPOKEN)
        return quadro

    def _blind_message(self) -> str:
        """A queixa de tela preta ajustada ao que se sabe do vídeo.

        A frase padrão manda trocar o modo de vídeo, e ela está certa na
        maioria das vezes. Mas quando o game.cfg foi encontrado e diz que
        o modo já não é tela cheia exclusiva, repetir esse conselho manda
        o jogador consertar o que não está quebrado — ele mexe no vídeo,
        a tela continua preta, e a conclusão é que o aviso não presta.
        """
        try:
            if self._config_path() is not None and not self._fullscreen():
                return BLIND_MODE_IS_FINE
        except Exception:  # pragma: no cover - rede de segurança
            pass
        return BLIND_MESSAGE

    def _screen_grab(self, rect):
        from .capture import ScreenGrabber

        if self._grabber is None:
            # Um grabber por thread: criar na thread que usa é o que o
            # próprio módulo de captura pede, tanto no DXGI quanto no GDI.
            self._grabber = ScreenGrabber()
        quadro = self._grabber.grab(rect)
        if getattr(self._grabber, "strategy", "") == "gdi":
            self._note("captura_gdi", NOTE_GDI)
        return quadro

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
