"""Ensaia o aviso do jungler inteiro sem precisar de uma partida aberta.

Monta uma tela falsa em volta de um minimapa verdadeiro, cola o retrato
real do jungler inimigo em pontos escolhidos do mapa e roda o
`JungleWatcher` de verdade em cima disso: mesma localizacao de minimapa,
mesma deteccao por molde, mesmas zonas, mesma voz.

So duas coisas entram falsificadas -- a captura de tela e a partida ao
vivo -- porque sao exatamente as duas que exigem o jogo aberto. Todo o
resto e o mesmo codigo que roda na partida.

Uso:
    py -3 tools/testar_aviso_jungler.py
    py -3 tools/testar_aviso_jungler.py --mudo
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lolqueue.vision import gamecfg, livegame
from lolqueue.vision import watcher as watcher_module
from lolqueue.vision.icons import ChampionIcons, circular_mask, resize
from lolqueue.vision.minimap import locate, search_area
from lolqueue.vision.voice import Voice, normalize_voice
from lolqueue.vision.watcher import ICON_FRACTION, JungleWatcher
from lolqueue.vision.window import Rect, viewport

FIXTURE = RAIZ / "tests" / "fixtures" / "minimap_sample.png"

# A tela falsa: resolucao comum, minimapa com margem, como o jogo faz.
TELA = Rect(0, 0, 1920, 1080)
MARGEM_X, MARGEM_Y = 12, 10

# Onde o jungler inimigo aparece, em coordenada de mapa (0..1), com
# (0, 1) na base azul e (1, 0) na vermelha.
PONTOS = [
    (0.62, 0.88, "colado na rota de baixo"),
    (0.30, 0.30, "la em cima, lado inimigo"),
    (0.50, 0.50, "no meio do mapa"),
    (0.78, 0.58, "selva de baixo, do lado azul"),
]

# O detector so confirma depois de tres quadros seguidos no mesmo ponto.
QUADROS = 4


def cena(mapa):
    """A tela falsa com o minimapa colado no canto inferior direito."""
    rng = np.random.default_rng(7)
    tela = np.full((TELA.height, TELA.width, 3), 12, np.uint8)
    tela += rng.integers(0, 6, tela.shape, dtype=np.uint8)
    lado = mapa.shape[0]
    y = TELA.height - lado - MARGEM_Y
    x = TELA.width - lado - MARGEM_X
    tela[y : y + lado, x : x + lado] = mapa
    return tela, x, y, lado


def colar_icone(tela, x0, y0, lado, retrato, mx, my):
    """Cola o retrato do campeao no ponto (mx, my) do minimapa."""
    tamanho = max(int(round(lado * ICON_FRACTION)), 1)
    icone = resize(retrato, tamanho).astype(np.uint8)
    mascara = circular_mask(tamanho)[:, :, None]
    cx = x0 + int(round(mx * lado))
    cy = y0 + int(round(my * lado))
    meio = tamanho // 2
    ax, ay = cx - meio, cy - meio
    alvo = tela[ay : ay + tamanho, ax : ax + tamanho]
    tela[ay : ay + tamanho, ax : ax + tamanho] = np.where(mascara, icone, alvo)
    return tamanho


def partida_falsa(campeao, rota, lado_azul):
    """Uma partida montada pelo parser de verdade, a partir de JSON cru."""
    meu_time = livegame.ORDER if lado_azul else livegame.CHAOS
    outro = livegame.CHAOS if lado_azul else livegame.ORDER
    lista = [
        {
            "riotId": "Ensaio#BR1",
            "championName": "Ashe",
            "team": meu_time,
            "position": rota,
        },
        {
            "riotId": "Inimigo#BR1",
            "championName": campeao,
            "team": outro,
            "position": livegame.JUNGLE,
        },
    ]
    return livegame.parse("Ensaio#BR1", lista)


class Relogio:
    """Tempo controlado: o ensaio roda em segundos de verdade, mas as
    regras de silencio do aviso precisam de tempo de partida."""

    def __init__(self, passo=1.0):
        self.agora = 1000.0
        self.passo = passo

    def __call__(self):
        return self.agora

    def avanca(self):
        self.agora += self.passo


class VozMuda:
    """Anota o que seria dito, sem tocar audio nenhum."""

    def __init__(self):
        self.ditas = []

    def say(self, texto):
        self.ditas.append(texto)
        return True

    def prime(self, frases):
        return 0

    def drain(self, timeout=5.0):
        return True

    def close(self):
        pass


def ambiente():
    print("=" * 68)
    print("1. AMBIENTE REAL (o que da para conferir com o jogo fechado)")
    print("=" * 68)

    vista = viewport()
    texto = str(vista) if vista else "nao achei (jogo fechado)"
    print("  janela do jogo ............ " + texto)

    try:
        cheia = gamecfg.exclusive_fullscreen()
        print("  tela cheia exclusiva ...... {0}  (True calaria o aviso)".format(cheia))
    except Exception as erro:
        print("  tela cheia exclusiva ...... erro ao ler game.cfg: {0}".format(erro))

    try:
        flip = gamecfg.flip_minimap()
        print("  minimapa invertido ........ {0}".format(flip))
    except Exception as erro:
        print("  minimapa invertido ........ erro: {0}".format(erro))

    try:
        jogo = livegame.fetch(timeout=1.0)
        print("  partida ao vivo (2999) .... {0}, lado {1}".format(jogo.lane_name, jogo.side))
    except livegame.LiveGameUnavailable as erro:
        print("  partida ao vivo (2999) .... indisponivel: {0}".format(erro))
    except Exception as erro:
        print("  partida ao vivo (2999) .... erro: {0}".format(erro))

    try:
        from lolqueue.vision.capture import ScreenGrabber

        grabber = ScreenGrabber()
        quadro = grabber.grab(Rect(0, 0, 320, 240))
        modo = grabber.strategy
        grabber.close()
        if quadro is None:
            print("  captura de tela ........... NAO capturou nada ({0})".format(modo))
        else:
            brilho = float(np.asarray(quadro).mean())
            print(
                "  captura de tela ........... {0} via {1}, brilho medio {2:.1f} "
                "(0 = tela preta)".format(tuple(quadro.shape), modo, brilho)
            )
    except Exception as erro:
        print("  captura de tela ........... erro: {0}".format(erro))
    print()


def ensaio(campeao, rota, lado_azul, mudo):
    print("=" * 68)
    print("2. PIPELINE COMPLETA EM MINIMAPA SINTETICO")
    print("=" * 68)

    from PIL import Image

    mapa = np.array(Image.open(FIXTURE).convert("RGB"))
    tela, x0, y0, lado = cena(mapa)
    limpo = tela.copy()

    icones = ChampionIcons()
    retrato = icones.portrait(campeao)
    if retrato is None:
        print("  !! nao consegui o retrato de {0} (sem cache e sem rede)".format(campeao))
        return 1
    print("  retrato de {0}: {1}px".format(campeao, retrato.shape[0]))

    jogo = partida_falsa(campeao, rota, lado_azul)
    cor = "azul" if jogo.side > 0 else "vermelho"
    print(
        "  partida: voce e {0} do lado {1}; jungler inimigo {2}".format(
            jogo.lane_name, cor, jogo.enemy_jungler.champion
        )
    )

    area = search_area(TELA)
    achado = locate(tela[area.y : area.bottom, area.x : area.right], area)
    if achado is None:
        print("  !! locate() nao achou o minimapa na cena")
        return 1
    print(
        "  minimapa localizado: {0}px em ({1}, {2}); colado com {3}px em ({4}, {5})".format(
            achado.rect.width, achado.rect.x, achado.rect.y, lado, x0, y0
        )
    )
    print()

    def grab(rect):
        return tela[rect.y : rect.y + rect.height, rect.x : rect.x + rect.width]

    relogio = Relogio()
    if mudo:
        voz = VozMuda()
    else:
        voz = Voice(normalize_voice(None), on_message=lambda m: print("    voz: " + str(m)))

    vistos = []
    real_announce = watcher_module.announce

    def espiao(champion, mx, my, game=None):
        vistos.append((mx, my))
        return real_announce(champion, mx, my, game)

    watcher_module.announce = espiao
    vigia = JungleWatcher(
        voz,
        icons=icones,
        on_message=lambda m: print("    diario: " + str(m)),
        viewport_fn=lambda: TELA,
        locate_fn=locate,
        grab_fn=grab,
        game_fn=lambda: jogo,
        clock=relogio,
        fullscreen_fn=lambda: False,
    )

    falhas = 0
    try:
        for mx, my, descricao in PONTOS:
            tela[:] = limpo
            colar_icone(tela, x0, y0, lado, retrato, mx, my)
            print("  > jungler em ({0:.2f}, {1:.2f}) -- {2}".format(mx, my, descricao))

            aviso = None
            for _ in range(QUADROS):
                aviso = vigia.tick() or aviso
                relogio.avanca()

            if aviso is None:
                print("    FALHOU: nenhum aviso saiu")
                falhas += 1
            else:
                dmx, dmy = vistos[-1]
                distancia = float(np.hypot(dmx - mx, dmy - my))
                marca = "ok" if distancia <= 0.02 else "LONGE DEMAIS"
                print(
                    "    detectado em ({0:.3f}, {1:.3f})  erro {2:.3f} [{3}]".format(
                        dmx, dmy, distancia, marca
                    )
                )
                print("    zona: {0}   urgencia: {1}".format(aviso.zone_key, aviso.urgency))
                print("    FALA: " + aviso.text)
                if distancia > 0.02:
                    falhas += 1
            print()
    finally:
        watcher_module.announce = real_announce

    if mudo:
        print("  frases que teriam sido faladas: {0}".format(len(voz.ditas)))
    else:
        print("  esperando o audio terminar...")
        inicio = time.monotonic()
        pronto = voz.drain(timeout=30.0)
        print("  audio drenado em {0:.1f}s (ok={1})".format(time.monotonic() - inicio, pronto))
        voz.close()

    return falhas


def ensaio_cego(mudo):
    """O cenario das partidas de 27/08: tela cheia exclusiva e captura preta.

    Aqui nao ha relogio falso nem tick manual: o laco de verdade sobe
    na thread de verdade e a gente ve se ele reclama sozinho, que era
    exatamente o que faltava naquelas quatro partidas.
    """
    print("=" * 68)
    print("3. CENARIO CEGO (tela cheia exclusiva, captura preta)")
    print("=" * 68)

    jogo = partida_falsa("Graves", livegame.BOT, True)
    recado = []

    def anota(m):
        recado.append(str(m))
        print("    diario: " + str(m))

    voz = VozMuda() if mudo else Voice(normalize_voice(None), on_message=lambda m: None)
    vigia = JungleWatcher(
        voz,
        icons=ChampionIcons(),
        on_message=anota,
        viewport_fn=lambda: TELA,
        locate_fn=locate,
        grab_fn=lambda rect: np.zeros((rect.height, rect.width, 3), np.uint8),
        game_fn=lambda: jogo,
        fullscreen_fn=lambda: True,
    )

    vigia.start()
    print("  laco ligado; esperando o aviso de cegueira (15s)...")
    time.sleep(19.0)
    vigia.stop()
    if not mudo:
        voz.drain(timeout=20.0)
        voz.close()

    junto = " | ".join(recado)
    falhas = 0
    if "cheia" not in junto and "bordas" not in junto:
        print("    FALHOU: nada avisou sobre o modo de video")
        falhas += 1
    if "prete" not in junto and "preta" not in junto and "ilegivel" not in junto.lower():
        print("    FALHOU: nada avisou que a captura veio preta")
        falhas += 1
    if falhas == 0:
        print("    ok: o laco reclamou sozinho, em vez de ficar mudo")
    print()
    return falhas


def main():
    parser = argparse.ArgumentParser(description="Ensaio do aviso do jungler.")
    parser.add_argument("--mudo", action="store_true", help="nao toca audio")
    parser.add_argument("--campeao", default="Graves", help="jungler inimigo")
    parser.add_argument("--rota", default=livegame.BOT, help="sua rota")
    parser.add_argument("--vermelho", action="store_true", help="voce no lado vermelho")
    parser.add_argument("--tela", default="1920x1080", help="resolucao da cena")
    parser.add_argument("--pular-cego", action="store_true", help="pula a parte 3")
    args = parser.parse_args()

    global TELA
    largura, _, altura = args.tela.lower().partition("x")
    TELA = Rect(0, 0, int(largura), int(altura))

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ambiente()
    print("  cena do ensaio ............ {0} por {1}".format(TELA.width, TELA.height))
    print()
    falhas = ensaio(args.campeao, args.rota, not args.vermelho, args.mudo)
    if not args.pular_cego:
        falhas += ensaio_cego(args.mudo)
    print("=" * 68)
    print("TUDO CERTO" if falhas == 0 else "{0} ponto(s) com problema".format(falhas))
    print("=" * 68)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
