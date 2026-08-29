"""Mede quantas frases faladas nomeiam o lugar ERRADO.

Por que uma ferramenta e não um teste: os testes provam que cada porta
do caminho (`_smooth`, `_steady`, `_due`) decide o que foi desenhado
para decidir. Nenhum deles responde à pergunta que o jogador faz, que é
outra e é um número — *de cada dez frases que o app fala, quantas
mandam o jungler para um lugar onde ele não está?*

O defeito medido aqui não vem da visão. `zones.classify` corta o mapa
em 29 nomes sem histerese nenhuma, e um terço da área fica a menos de
0,02 de uma divisa. Sobre uma dessas linhas o pico da correlação treme
dois pixels, o nome do lugar troca, e a voz descreve uma ida e volta
que nunca aconteceu. A leitura estava certa; o nome é que não estava.

O que roda aqui é o código de verdade — `JungleWatcher.tick`, o
`announce` de verdade, as zonas de verdade. O que é dublado é só o que
precisa de placa de vídeo: a captura, o recorte do minimapa e o
casamento do retrato. O detector devolve a posição verdadeira somada a
um tremor gaussiano, que é exatamente o que o casamento faz na partida.

Duas receitas correm o mesmo trajeto:

  antes  -- o comportamento anterior ao conserto: sem mediana, e a
            trava de zona valendo só contra o quadro anterior, com
            "cuidado" furando a fila sempre.
  agora  -- o código como está no disco.

Roda: py -3 tools/medir_avisos.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lolqueue.vision.callout import PERTO, announce
from lolqueue.vision.detect import Match
from lolqueue.vision.minimap import Minimap
from lolqueue.vision.watcher import JungleWatcher
from lolqueue.vision.window import Rect
from lolqueue.vision.zones import place

FPS = 5.0
PASSO = 1.0 / FPS
QUADROS = 3000  # 10 minutos
LADO = 280  # o minimapa em pixels, como numa tela 1080p
VELOCIDADE = 0.027 / FPS  # fração do mapa por quadro, campeão andando
TREMORES = (0.002, 0.005, 0.010)
SEMENTES = (11, 23, 37)

#: Quantos quadros de folga o nome ganha antes de contar como errado.
#: A mediana atrasa a leitura de propósito; um nome certo com meio
#: segundo de atraso não é a mesma falta que um nome que nunca foi
#: verdade, e misturar os dois esconderia o preço do conserto.
FOLGA = 2

QUADRO = np.full((LADO, LADO, 3), 40, np.uint8)


class _Voz:
    """Uma voz que não fala nada e anota tudo."""

    def __init__(self) -> None:
        self.ditas: list[str] = []

    def say(self, texto, ttl=None, group="") -> None:
        self.ditas.append(texto)


class _Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


class _Detector:
    """O casamento do retrato, já sabendo onde ele estava."""

    def __init__(self) -> None:
        self.achado: Match | None = None

    def feed(self, quadro):
        return self.achado


def jogo(lane: str, ancora: tuple[float, float], lado: int = 1):
    """Uma partida em curso, do ponto de vista de quem está ouvindo."""
    return SimpleNamespace(
        side=lado,
        lane=lane,
        lane_name=lane,
        enemy_jungler=SimpleNamespace(champion="Lee Sin"),
        jungler_has_a_twin=False,
        me=SimpleNamespace(is_jungler=False),
        anchor_is_a_guess=False,
        my_anchor=ancora,
        to_world=lambda mx, my: (mx, my),
    )


def rota_jungler(n: int) -> list[tuple[float, float]]:
    """Um trajeto plausível: acampamentos, rio, gank, volta.

    As paradas importam tanto quanto os passos: um jungler farmando um
    acampamento fica parado uns doze segundos, e é parado em cima de uma
    divisa que o app antigo mais errava.
    """
    marcos = [
        (0.30, 0.72), (0.24, 0.62), (0.32, 0.55), (0.42, 0.60),
        (0.50, 0.52), (0.58, 0.42), (0.68, 0.32), (0.76, 0.26),
        (0.66, 0.20), (0.52, 0.30), (0.40, 0.42), (0.30, 0.50),
        (0.20, 0.60), (0.14, 0.78), (0.30, 0.86), (0.48, 0.78),
    ]
    pos = np.array(marcos[0], float)
    alvo_i, parado, saida = 1, 0, []
    for _ in range(n):
        if parado > 0:
            parado -= 1
        else:
            alvo = np.array(marcos[alvo_i % len(marcos)], float)
            d = alvo - pos
            dist = float(np.hypot(*d))
            if dist < VELOCIDADE:
                alvo_i += 1
                parado = 60  # doze segundos farmando
            else:
                pos = pos + d / dist * VELOCIDADE
        saida.append((float(pos[0]), float(pos[1])))
    return saida


def montar(partida, relogio, detector, mapa) -> JungleWatcher:
    vigia = JungleWatcher(
        voice=_Voz(),
        on_message=lambda _t: None,
        viewport_fn=lambda: Rect(0, 0, 1920, 1080),
        locate_fn=lambda frame, area, flipped=False: mapa,
        grab_fn=lambda rect: QUADRO,
        game_fn=lambda: partida,
        clock=relogio,
        fullscreen_fn=lambda: False,
        config_fn=lambda: Path("game.cfg"),
    )
    vigia._minimap = mapa
    vigia._minimap_at = 0.0
    vigia._detector = detector
    vigia._champion = "Lee Sin"
    return vigia


def envelhecer(vigia: JungleWatcher) -> None:
    """Devolve a vigilância ao comportamento anterior ao conserto.

    Não é uma reconstrução de memória: as duas peças abaixo são cópia
    literal do que estava em `watcher.py` no commit anterior — o `tick`
    lia `to_map` direto, sem mediana, e o `_steady` comparava a zona só
    com a do quadro anterior, deixando qualquer "cuidado" passar.
    """
    vigia._smooth = lambda mx, my: (mx, my)
    estado = {"zona": ""}

    def steady_antigo(aviso) -> bool:
        anterior = estado["zona"]
        estado["zona"] = aviso.zone_key
        return aviso.urgency == PERTO or not anterior or aviso.zone_key == anterior

    def esquecer() -> None:
        estado["zona"] = ""

    vigia._steady = steady_antigo
    vigia._forget_zone = esquecer


def medir(
    receita: str,
    lane: str,
    ancora,
    tremor: float,
    semente: int,
    quadros: int = QUADROS,
) -> dict:
    rota = rota_jungler(quadros)
    verdade = [place(x, y) for x, y in rota]

    relogio = _Relogio()
    detector = _Detector()
    mapa = Minimap(rect=Rect(1600, 800, LADO, LADO), flipped=False)
    vigia = montar(jogo(lane, ancora), relogio, detector, mapa)
    if receita == "antes":
        envelhecer(vigia)

    rng = np.random.default_rng(semente)
    ditas: list[tuple[int, tuple[str, int]]] = []
    for i, (x, y) in enumerate(rota):
        dx, dy = rng.normal(0.0, tremor, 2)
        mx = min(max(x + dx, 0.0), 1.0)
        my = min(max(y + dy, 0.0), 1.0)
        detector.achado = Match(
            x=mx * LADO, y=my * LADO, score=0.93, size=21, margin=0.22
        )
        relogio.agora = PASSO * (i + 1)
        aviso = vigia.tick()
        if aviso is not None:
            ditas.append((i, (aviso.zone_key, aviso.zone_side)))

    estrito = sum(1 for i, lugar in ditas if lugar != verdade[i])
    tolerante = 0
    for i, lugar in ditas:
        janela = verdade[max(i - FOLGA, 0) : i + FOLGA + 1]
        if lugar not in janela:
            tolerante += 1

    # Vai-e-vem: dizer A, dizer B, dizer A de novo em menos de seis
    # segundos. É a forma que o defeito toma no ouvido de quem joga —
    # não uma frase errada isolada, mas o jungler teleportando.
    vaivem = 0
    for a, b, c in zip(ditas, ditas[1:], ditas[2:]):
        if a[1] == c[1] and a[1] != b[1] and (c[0] - a[0]) * PASSO <= 6.0:
            vaivem += 1

    minutos = quadros * PASSO / 60.0
    return {
        "ditas": len(ditas),
        "estrito": estrito,
        "tolerante": tolerante,
        "vaivem": vaivem,
        "taxa": 100.0 * estrito / max(len(ditas), 1),
        "taxa_tol": 100.0 * tolerante / max(len(ditas), 1),
        "certas_min": (len(ditas) - tolerante) / minutos,
        "trocas_reais": sum(1 for a, b in zip(verdade, verdade[1:]) if a != b),
    }


def media(chaves, linhas) -> dict:
    return {k: sum(l[k] for l in linhas) / len(linhas) for k in chaves}


def main() -> None:
    minutos = QUADROS * PASSO / 60.0
    print(f"trajeto de {QUADROS} quadros a {FPS:g} fps = {minutos:.0f} min")
    rota = rota_jungler(QUADROS)
    verdade = [place(x, y) for x, y in rota]
    trocas = sum(1 for a, b in zip(verdade, verdade[1:]) if a != b)
    print(f"o campeão realmente muda de zona {trocas} vezes no trajeto")
    print(f"média de {len(SEMENTES)} sementes por célula\n")

    chaves = ("ditas", "estrito", "tolerante", "vaivem", "taxa", "taxa_tol", "certas_min")
    perfis = (
        ("quem ouve joga no MEIO", "MIDDLE", (0.50, 0.50)),
        ("quem ouve joga em CIMA", "TOP", (0.13, 0.13)),
    )

    for titulo, lane, ancora in perfis:
        print("=" * 78)
        print(titulo)
        print("=" * 78)
        print(
            f"{'tremor':>7} {'receita':>8} {'faladas':>8} {'erradas':>8} "
            f"{'erro%':>7} {'erro% c/ folga':>15} {'vai-e-vem':>10} "
            f"{'certas/min':>11}"
        )
        for tremor in TREMORES:
            for receita in ("antes", "agora"):
                linhas = [
                    medir(receita, lane, ancora, tremor, s) for s in SEMENTES
                ]
                m = media(chaves, linhas)
                print(
                    f"{tremor:>7.3f} {receita:>8} {m['ditas']:>8.0f} "
                    f"{m['estrito']:>8.0f} {m['taxa']:>7.1f} "
                    f"{m['taxa_tol']:>15.1f} {m['vaivem']:>10.0f} "
                    f"{m['certas_min']:>11.1f}"
                )
        print()


if __name__ == "__main__":
    main()
