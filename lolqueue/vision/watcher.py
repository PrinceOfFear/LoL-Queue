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
from dataclasses import dataclass
from typing import Callable

from . import gamecfg
from . import minimap as minimap_module
from . import window as window_module
from .callout import LONGE, MEDIO, PERTO, REPEAT_SECONDS
from .callout import Callout, all_phrases, announce
from .detect import (
    ACQUIRE_MARGIN,
    CONFIRM_FRAMES,
    FORGIVE_FRAMES,
    JUMP_FRACTION,
    MARGIN,
    THRESHOLD,
    Detector,
)
from .icons import ChampionIcons
from .livegame import LiveGame, LiveGameUnavailable
from .livegame import fetch as fetch_game
from .zones import STABLE_MARGIN

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

#: A ordem em que os avisos se atropelam. Existe porque o piso acima era
#: cego ao conteúdo: um "no rio de baixo, longe de você" segurava por dois
#: segundos e meio o "cuidado, na sua selva de cima" que veio logo atrás,
#: e esses dois segundos e meio são a diferença entre recuar e morrer.
#: Aviso mais grave que o anterior fura o piso; menos grave espera, como
#: sempre esperou.
URGENCY_RANK = {LONGE: 0, MEDIO: 1, PERTO: 2}

# Quantos quadros entram na mediana da posição antes de perguntar em que
# zona o ícone está. A cinco quadros por segundo, cinco é um segundo de
# janela: o bastante para o tremor do casamento sumir e pouco para um
# Flash aparecer, já que a mediana ignora um salto isolado e acompanha
# um deslocamento que se mantém.
SMOOTH_FRAMES = 5

# Quadros seguidos que uma zona nova precisa somar antes de valer. A cinco
# quadros por segundo são 0,6 s de posição consistente depois que o retrato
# já passou pela confirmação do detector.
STEADY_FRAMES = 3

# A válvula da teimosia. Um campeão pode parar exatamente em cima de uma
# divisa, e aí a folga espacial nunca se cumpre: sem esta saída o nome
# antigo ficaria valendo até ele sair dali. Três segundos insistindo na
# mesma zona valem mais que a folga — antes disso, uma borda é dúvida, não
# localização.
STUBBORN_FRAMES = 15


@dataclass(frozen=True)
class JunglePrecisionPolicy:
    """Quanto de prova uma localização precisa antes de ganhar voz.

    A escolha fica reunida para que o modo máximo seja de verdade uma
    regra completa: detector, movimento, mediana e divisa precisam ser
    conservadores juntos. Apertar só uma dessas portas apenas desloca o
    falso aviso para a próxima.
    """

    threshold: float
    margin: float
    acquire_margin: float
    confirm_frames: int
    forgive_frames: int
    jump_fraction: float
    smooth_frames: int
    steady_frames: int
    stubborn_frames: int | None
    stable_margin: float
    firm_probes: int


# O perfil histórico: mantém a resposta rápida para quem desmarca a
# precisão máxima nas configurações. Os nomes públicos acima continuam
# existindo porque são a régua dos testes e da documentação.
NORMAL_PRECISION = JunglePrecisionPolicy(
    threshold=THRESHOLD,
    margin=MARGIN,
    acquire_margin=ACQUIRE_MARGIN,
    confirm_frames=CONFIRM_FRAMES,
    forgive_frames=FORGIVE_FRAMES,
    jump_fraction=JUMP_FRACTION,
    smooth_frames=SMOOTH_FRAMES,
    steady_frames=STEADY_FRAMES,
    stubborn_frames=STUBBORN_FRAMES,
    stable_margin=STABLE_MARGIN,
    firm_probes=8,
)

# Preferir calar a adivinhar. Este perfil exige cinco imagens consecutivas
# do mesmo retrato, não carrega um rastro por cima de um quadro perdido e
# recusa uma mudança rápida demais para um campeão. A margem de zona e as
# 16 sondas deixam toda a vizinhança de uma divisa em silêncio.
MAX_PRECISION = JunglePrecisionPolicy(
    threshold=0.90,
    margin=0.10,
    acquire_margin=0.14,
    confirm_frames=5,
    forgive_frames=0,
    jump_fraction=0.20,
    smooth_frames=7,
    steady_frames=5,
    stubborn_frames=None,
    stable_margin=0.025,
    firm_probes=16,
)

#: Quanto tempo um aviso do jungler ainda vale depois de calculado.
#: Passado o prazo sem ter começado a tocar, ele é descartado em vez de
#: dito: a fila da voz não é instantânea, e um aviso atrasado não é um
#: aviso fraco — é uma informação falsa sobre onde o inimigo está.
CALLOUT_SECONDS = 4.0

#: O assunto dos avisos do jungler, para que um aviso novo cale o que
#: ainda não foi dito sobre o mesmo campeão. Ver `Voice.say`.
CALLOUT_TOPIC = "jungler"

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
    "A captura rápida (DXGI), que é a única que enxerga o jogo em tela "
    "cheia exclusiva, não está funcionando nesta máquina — sigo tentando "
    "religar ela sozinho. Se o aviso não voltar, atualize o driver de "
    'vídeo ou, como remendo, troque o Modo de Vídeo para "Sem bordas" '
    "em Opções > Vídeo."
)

#: A tela preta com a captura rápida funcionando. Aqui a tela cheia
#: está fora de suspeita — o DXGI lê tela cheia exclusiva sem problema
#: — e mandar o jogador trocar o modo de vídeo seria jogá-lo contra a
#: parede errada. O que sobra são as causas que apagam o quadro antes
#: de ele chegar na captura.
BLIND_ON_DXGI = (
    "Não consegui ler a tela do jogo: a captura está vindo toda preta, "
    "mesmo com a captura rápida (DXGI) ligada. O modo de vídeo não é o "
    "problema — tela cheia exclusiva funciona. Nesses casos a causa "
    "costuma ser HDR do Windows ligado, um overlay por cima do jogo "
    "(Discord, GeForce Experience) ou o jogo rodando numa placa de "
    "vídeo diferente da que o app captura."
)

#: A mesma tela preta, quando o game.cfg já disse que o modo de vídeo
#: não é o culpado. Mandar trocar uma opção que já está certa é pior do
#: que não dizer nada: o jogador mexe no vídeo, nada muda, e ele conclui
#: que o aviso é quebrado — quando a pista verdadeira estava em outro
#: lugar o tempo todo.
BLIND_MODE_IS_FINE = (
    "Não consegui ler a tela do jogo: a captura está vindo toda preta. "
    "O modo de vídeo não é o problema — conferi no game.cfg e ele nem "
    "está em tela cheia exclusiva, que de todo modo é suportada. "
    "Nesses casos a causa costuma ser o "
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
    "A captura rápida (DXGI) falhou e caí para o método antigo (GDI), "
    "que é mais lento e vem preto por cima de um jogo em tela cheia "
    "exclusiva. Não é definitivo: enquanto o GDI estiver devolvendo "
    "preto, tento o DXGI de novo a cada 15 segundos. Se o aviso do "
    "jungler ficar mudo nesta partida, comece a investigação por aqui."
)

#: O mesmo recado, dito antes de custar uma partida. O game.cfg diz o
#: modo de vídeo sem precisar de um único quadro, então quando ele já
#: acusa tela cheia exclusiva não há motivo para esperar quinze segundos
#: de silêncio para explicar o silêncio. Sai uma vez, ao ligar.
NOTE_FULLSCREEN = (
    "O jogo está em tela cheia exclusiva. É suportado: a captura rápida "
    "(DXGI) lê esse modo direto da placa de vídeo. Se ela falhar, o "
    "diário avisa aqui mesmo em vez de o aviso simplesmente emudecer."
)

#: A notícia dita em voz alta. O registro em arquivo não chega a quem
#: está dentro da partida — e o jogador que não escuta nada conclui que
#: o app está quebrado, não que está cego. Curta de propósito: uma
#: frase, uma vez, e nunca durante uma luta. Não manda trocar o modo de
#: vídeo: a tela cheia exclusiva é suportada, e o conselho reflexo de
#: sair dela atrapalhava quem joga assim sem sequer ser a causa.
BLIND_SPOKEN = (
    "Não consigo ler a tela do jogo; o aviso do jungler pode falhar. "
    "O motivo está no diário."
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
        debug: bool = False,
        max_precision: bool = False,
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
        # Guardar o raciocínio de cada aviso ao lado dele no registro.
        # Desligado por padrão: uma linha dessas por aviso é ruído para
        # quem só quer jogar, e é a única coisa que responde "por que
        # ele falou isso?" para quem foi conferir depois da partida.
        self._debug = bool(debug)
        # A sessão do app escolhe o perfil pela configuração. O construtor
        # fica equilibrado por padrão para integrações que já o usam direto;
        # o produto liga este modo conservador pela configuração nova.
        self._max_precision = bool(max_precision)
        self._precision = (
            MAX_PRECISION if self._max_precision else NORMAL_PRECISION
        )

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
        # Zona -> (quando foi dita, o quanto era grave). A gravidade
        # entra na conta para que o mesmo lugar possa ser dito de novo
        # quando ele passa de notícia a perigo.
        self._said: dict[str, tuple[float, int]] = {}
        self._last_said = 0.0
        self._last_level = 0
        # Posição, zona sustentada e zona candidata: ver `_smooth` e
        # `_steady`.
        self._recent: list[tuple[float, float]] = []
        self._zone_seen: tuple[str, int] | None = None
        self._zone_streak = 0
        self._zone_hold: tuple[str, int] | None = None
        self._zone_level = 0
        self._blind_since: float | None = None
        self._blind_warned = False
        # Qual captura respondeu por último: "dxgi", "gdi" ou vazio
        # enquanto ninguém capturou nada (ou o grab veio injetado).
        self._strategy = ""
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
        """Registra o modo de vídeo, sem transformá-lo em acusação.

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
                self._log(NOTE_FULLSCREEN)
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
        self._last_level = 0
        self._forget_zone()
        self._blind_since = None
        self._blind_warned = False
        self._strategy = ""
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
            # Perdeu o rastro: a próxima zona é um novo avistamento e
            # precisa provar que não caiu na divisa. A janela da mediana
            # vai junto — misturar o antes e o depois de um sumiço
            # inventa uma posição intermediária que o campeão nunca
            # ocupou.
            self._forget_zone()
            return None

        mx, my = self._smooth(*mapa.to_map(achado.x, achado.y))
        aviso = announce(
            jungler.champion,
            mx,
            my,
            jogo,
            stable_margin=self._precision.stable_margin,
            firm_probes=self._precision.firm_probes,
        )
        if not self._steady(aviso) or not self._due(aviso, agora):
            return None
        nivel = URGENCY_RANK.get(aviso.urgency, 1)
        self._said[aviso.zone_key] = (agora, nivel)
        self._last_said = agora
        self._last_level = nivel
        self._speak(aviso.text, ttl=CALLOUT_SECONDS, group=CALLOUT_TOPIC)
        self._log(aviso.text)
        self._explain(aviso, achado, mapa, mx, my, jogo)
        return aviso

    def _explain(self, aviso, achado, mapa, mx, my, jogo) -> None:
        """Registra de onde saiu o aviso que acabou de ser falado.

        Um aviso errado pode ter três causas, e a frase falada não
        distingue nenhuma delas: o retrato foi achado onde não estava
        (nitidez e folga baixas), foi achado no lugar certo e o mapa de
        zonas nomeou errado (coordenada certa, zona torta), ou o lugar
        está certo e a urgência é que não (âncora chutada). Cada número
        aqui separa um desses casos, e é barato: só sai quando o
        diagnóstico está ligado, e só uma vez por aviso.
        """
        if not self._debug:
            return
        try:
            wx, wy = jogo.to_world(mx, my)
            ax, ay = jogo.my_anchor
            self._log(
                f"[diagnóstico] {aviso.zone_key} · {aviso.urgency} · "
                f"mapa ({mx:.3f}, {my:.3f}) · mundo ({wx:.3f}, {wy:.3f}) · "
                f"eu em ({ax:.3f}, {ay:.3f})"
                f"{' chutado' if jogo.anchor_is_a_guess else ''} "
                f"lado {jogo.side} rota {jogo.lane or '?'} · "
                f"nitidez {achado.score:.3f} folga {achado.margin:.3f} · "
                f"retrato {achado.size}px em ({achado.x}, {achado.y}) de "
                f"{mapa.rect.width}px"
                f"{' · minimapa girado' if mapa.flipped else ''}"
            )
        except Exception:  # pragma: no cover - rede de segurança
            # Diagnóstico nenhum vale um quadro perdido no meio da
            # partida, muito menos a vigilância inteira caindo.
            pass

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
        self._detector = Detector(
            moldes,
            threshold=self._precision.threshold,
            confirm=self._precision.confirm_frames,
            forgive=self._precision.forgive_frames,
            margin=self._precision.margin,
            acquire=self._precision.acquire_margin,
            jump_fraction=self._precision.jump_fraction,
        )
        return self._detector

    def _forget_zone(self) -> None:
        """Esquece onde ele estava. Usado quando o rastro se perde."""
        self._recent.clear()
        self._zone_seen = None
        self._zone_streak = 0
        self._zone_hold = None
        self._zone_level = 0

    def _smooth(self, mx: float, my: float) -> tuple[float, float]:
        """A mediana das últimas posições, em vez da última posição.

        O pico da correlação não para quieto: entre um quadro e outro ele
        anda um ou dois pixels sem o campeão ter saído do lugar. Sobre a
        divisa de duas zonas esse tremor vira nome trocado, e é o que a
        voz entrega como "ele foi para outro lugar".

        Mediana, e não média, por causa do Flash e do quadro solitário em
        que o casamento cai num pedaço parecido do mapa: a média seria
        puxada para um ponto onde ninguém esteve, enquanto a mediana
        descarta o intruso e só se move quando a nova posição vira
        maioria.
        """
        self._recent.append((mx, my))
        del self._recent[:-self._precision.smooth_frames]
        xs = sorted(p[0] for p in self._recent)
        ys = sorted(p[1] for p in self._recent)
        meio = len(xs) // 2
        if len(xs) % 2:
            return xs[meio], ys[meio]
        return (xs[meio - 1] + xs[meio]) / 2.0, (ys[meio - 1] + ys[meio]) / 2.0

    def _steady(self, aviso: Callout) -> bool:
        """Se a zona deste quadro já se firmou o bastante para ser dita.

        `zones` não tem histerese, e um terço do mapa fica colado numa
        divisa. Sobre uma delas o tremor do casamento troca o nome do
        lugar sem o campeão andar nada — medindo dez minutos de trajeto,
        o app dizia de quatro a doze vezes mais nomes diferentes do que
        o campeão visitou, e uma frase falada em cada cinco a cada três
        nomeava o lugar errado. Era isso, e não a visão, que fazia o
        aviso parecer chute: a leitura estava certa e o nome não.

        A trava tem três portas, e a ordem entre elas é o desenho todo:

        - a zona já sustentada continua valendo quando a leitura segue
          firme; se ela cai na divisa, preservamos o estado, mas não
          repetimos uma localização incerta;
        - uma leitura firme pode inaugurar uma zona, ou aumentar para
          "Cuidado", sem perder tempo;
        - toda leitura em uma divisa espera três quadros coerentes e
          continua esperando a folga espacial. Só três segundos no mesmo
          lado tornam uma borda insistente em localização.

        O detalhe de "firme" vale também para a primeira leitura e para a
        subida de urgência. Esses dois atalhos antes furavam a defesa da
        borda e eram justamente a origem de avisos falsos que soavam
        confiantes.
        """
        lugar = (aviso.zone_key, aviso.zone_side)
        nivel = URGENCY_RANK.get(aviso.urgency, 1)

        if lugar == self._zone_seen:
            self._zone_streak += 1
        else:
            self._zone_seen = lugar
            self._zone_streak = 1

        if self._max_precision:
            # Nem a primeira leitura nem um novo "Cuidado" fura a prova.
            # O detector já confirmou o retrato; estas cinco leituras firmes
            # confirmam também o NOME da região. Uma divisa persistente fica
            # muda de propósito, pois escolher um lado seria adivinhar.
            if not aviso.firm or self._zone_streak < self._precision.steady_frames:
                return False
            self._hold(lugar, nivel)
            return True

        if self._zone_hold is None or lugar == self._zone_hold:
            if aviso.firm:
                self._hold(lugar, nivel)
                return True
            if (
                self._precision.stubborn_frames is not None
                and self._zone_streak >= self._precision.stubborn_frames
            ):
                self._hold(lugar, nivel)
                return True
            return False
        if nivel > self._zone_level and aviso.firm:
            self._hold(lugar, nivel)
            return True
        if self._zone_streak < self._precision.steady_frames:
            return False
        if aviso.firm or (
            self._precision.stubborn_frames is not None
            and self._zone_streak >= self._precision.stubborn_frames
        ):
            self._hold(lugar, nivel)
            return True
        return False

    def _hold(self, lugar: tuple[str, int], nivel: int) -> None:
        self._zone_hold = lugar
        self._zone_level = nivel

    def _due(self, aviso: Callout, agora: float) -> bool:
        """Se este aviso pode ser dito agora, ou se atropela o anterior.

        Os dois silêncios daqui — não repetir a mesma zona, não falar por
        cima de si mesmo — eram cegos ao que estava sendo dito, e o preço
        era o pior possível: o aviso segurado era o mais grave, porque é o
        que costuma vir depois. Agora os dois valem só contra avisos de
        gravidade igual ou maior. Calar sobre um perigo para não
        interromper uma notícia é a troca errada.
        """
        nivel = URGENCY_RANK.get(aviso.urgency, 1)
        anterior = self._said.get(aviso.zone_key)
        if anterior is not None:
            quando, antes = anterior
            if agora - quando < REPEAT_SECONDS and nivel <= antes:
                return False
        if (
            self._last_said
            and agora - self._last_said < MIN_GAP_SECONDS
            and nivel <= self._last_level
        ):
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

        Três respostas para o mesmo sintoma, porque três causas
        diferentes o produzem. Com o DXGI de pé, a tela cheia está
        inocente por construção. Com o game.cfg dizendo que o modo nem é
        tela cheia, também. Só sobra o conselho do modo de vídeo quando
        a captura caiu para o GDI e nada desmente a tela cheia — e mesmo
        aí ele é o remendo, não o conserto: o app continua tentando
        religar o DXGI sozinho.
        """
        if self._strategy == "dxgi":
            # A captura que enxerga tela cheia está de pé e mesmo assim
            # o quadro veio preto: a culpa é de outra coisa.
            return BLIND_ON_DXGI
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
        self._strategy = getattr(self._grabber, "strategy", "")
        if self._strategy == "gdi":
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

    def _speak(self, text: str, ttl: float | None = None, group: str = "") -> None:
        """Fala sem deixar a voz derrubar o laço que a chamou.

        `ttl` e `group` são dos avisos do jungler, que descrevem um
        instante e envelhecem na fila; os recados do app não levam nenhum
        dos dois, porque continuam verdadeiros depois.
        """
        try:
            self._voice.say(text, ttl=ttl, group=group)
        except TypeError:  # pragma: no cover - voz antiga ou dublê
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
