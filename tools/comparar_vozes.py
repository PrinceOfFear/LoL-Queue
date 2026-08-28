"""Toca a mesma frase de aviso em varias vozes, para escolher de ouvido.

A diccao e o que importa aqui: o nome do campeao e a unica palavra da
frase que o jogador nao pode perder, e ele quase sempre vem do ingles.
As vozes multilingues sao a geracao nova do servico e pronunciam esses
nomes sem mastigar.

Uso:
    py -3 tools/comparar_vozes.py
    py -3 tools/comparar_vozes.py --rate -10%
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lolqueue.vision.voice import play_file

CANDIDATAS = [
    ("pt-BR-AntonioNeural", "Antonio, a voz de hoje"),
    ("pt-BR-FranciscaNeural", "Francisca"),
    ("pt-BR-ThalitaMultilingualNeural", "Thalita multilingue"),
    ("en-US-AndrewMultilingualNeural", "Andrew multilingue"),
    ("en-US-BrianMultilingualNeural", "Brian multilingue"),
    ("en-US-EmmaMultilingualNeural", "Emma multilingue"),
    ("en-US-AvaMultilingualNeural", "Ava multilingue"),
    ("fr-FR-RemyMultilingualNeural", "Remy multilingue"),
]

# Frases de teste: nomes de campeao dificeis e uma frase inteira.
FRASES = [
    "Cuidado, Warwick na rota de baixo, do seu lado",
    "Kha'Zix no covil do Barão, longe de você",
    "Nidalee na selva de cima dele",
]

SAIDA = RAIZ / "docs" / "amostras-voz"


def sintetiza(texto, voz, rate, pitch):
    import edge_tts

    dados = bytearray()
    fala = edge_tts.Communicate(texto, voz, rate=rate, pitch=pitch)
    for pedaco in fala.stream_sync():
        if pedaco.get("type") == "audio":
            dados += pedaco.get("data") or b""
    return bytes(dados)


def main():
    p = argparse.ArgumentParser(description="Compara vozes de aviso.")
    p.add_argument("--rate", default="+0%", help="velocidade, ex: -10%%")
    p.add_argument("--pitch", default="+0Hz", help="tom, ex: -20Hz")
    p.add_argument("--so-gerar", action="store_true", help="nao toca, so salva")
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    SAIDA.mkdir(parents=True, exist_ok=True)
    marca = "r{0}_p{1}".format(args.rate, args.pitch).replace("%", "").replace("+", "")

    tarefas = []
    for voz, rotulo in CANDIDATAS:
        curto = voz.split("-")[-1].replace("Neural", "")
        tarefas.append((voz, curto, "00-nome", "Voz " + rotulo))
        for i, frase in enumerate(FRASES, 1):
            tarefas.append((voz, curto, "{0:02d}".format(i), frase))

    print("sintetizando {0} audios (rate {1}, pitch {2})...".format(
        len(tarefas), args.rate, args.pitch))

    def trabalho(t):
        voz, curto, indice, texto = t
        destino = SAIDA / "{0}_{1}_{2}.mp3".format(curto, marca, indice)
        if not destino.exists():
            dados = sintetiza(texto, voz, args.rate, args.pitch)
            if not dados:
                return None
            destino.write_bytes(dados)
        return (curto, indice, destino)

    with ThreadPoolExecutor(max_workers=6) as pool:
        prontos = [r for r in pool.map(trabalho, tarefas) if r]

    print("salvos em: {0}\n".format(SAIDA))
    if args.so_gerar:
        return 0

    por_voz = {}
    for curto, indice, destino in prontos:
        por_voz.setdefault(curto, []).append((indice, destino))

    for voz, rotulo in CANDIDATAS:
        curto = voz.split("-")[-1].replace("Neural", "")
        faixas = sorted(por_voz.get(curto, []))
        if not faixas:
            print("  {0}: falhou a sintese".format(rotulo))
            continue
        print("  >> {0}   ({1})".format(rotulo, voz))
        for _, destino in faixas:
            play_file(destino)
    print("\nme diga qual soou melhor e eu deixo ela como padrao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
