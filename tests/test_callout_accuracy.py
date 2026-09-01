"""O aviso do jungler nomeia o lugar certo? — a medida, não as peças.

Os outros testes provam que cada porta do caminho decide o que foi
desenhada para decidir: a mediana devolve a mediana, a trava de zona
segura a zona trêmula, o piso entre avisos não deixa a voz atropelar a
si mesma. Nenhum deles responde à única pergunta que o jogador faz, e
que é um número: *de cada dez frases faladas, quantas mandam o jungler
para um lugar onde ele não está?*

Esse número já foi de um em cinco, e foi ele — não a visão — que fez o
aviso parecer chute. A leitura do minimapa estava certa; o nome do
lugar é que trocava, porque `zones` corta o mapa em 29 nomes sem
histerese nenhuma e um terço da área fica colado numa divisa.

O trajeto, o tremor e a contagem moram em `tools/medir_avisos.py`, que
é a mesma ferramenta que se roda à mão para investigar. O teste importa
o arquivo pelo caminho porque `tools/` não é pacote — e vale a
importação estranha para que a régua daqui e a da investigação sejam
literalmente a mesma, em vez de duas cópias que divergem na primeira
vez que alguém mexer numa delas.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

FERRAMENTA = Path(__file__).resolve().parent.parent / "tools" / "medir_avisos.py"


def _medidor():
    spec = importlib.util.spec_from_file_location("medir_avisos", FERRAMENTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


MEDIR = _medidor()

#: Tremor do casamento, em fração do mapa. 0,005 é o que se vê num
#: minimapa de 280px com o retrato bem casado; 0,010 é o dia ruim —
#: névoa por cima, retrato em escala errada, tela comprimida.
NORMAL = 0.005
RUIM = 0.010
LEVE = 0.002

SEMENTES = (11, 23, 37)

PERFIS = (("MIDDLE", (0.50, 0.50)), ("TOP", (0.13, 0.13)))


def _taxas(receita: str, tremor: float):
    """Erro e cobertura de cada perfil, em média sobre as sementes."""
    saida = []
    for lane, ancora in PERFIS:
        linhas = [
            MEDIR.medir(receita, lane, ancora, tremor, s) for s in SEMENTES
        ]
        saida.append(
            (
                lane,
                sum(l["taxa"] for l in linhas) / len(linhas),
                sum(l["certas_min"] for l in linhas) / len(linhas),
            )
        )
    return saida


@pytest.mark.parametrize("tremor,teto", [(NORMAL, 8.0), (RUIM, 12.0)])
def test_most_of_what_is_said_names_the_right_place(tremor, teto):
    """O teto é o que separa "ajuda" de "confunde".

    Um aviso errado não custa só a frase errada: quem ouve age nela.
    Um em cinco errado é o app que o jogador desliga; abaixo de um em
    dez ele volta a ser um par de olhos a mais.
    """
    for lane, taxa, _cobertura in _taxas("agora", tremor):
        assert taxa <= teto, f"{lane}: {taxa:.1f}% de frases erradas"


@pytest.mark.parametrize("tremor", [NORMAL, RUIM])
def test_being_careful_did_not_make_the_app_quiet(tremor):
    """Calar sempre também zera o erro, e seria o pior conserto possível.

    Nove avisos certos por minuto é o que o app dava antes de qualquer
    trava; o piso aqui existe para que uma trava futura não compre
    precisão vendendo silêncio.
    """
    for lane, _taxa, cobertura in _taxas("agora", tremor):
        assert cobertura >= 7.0, f"{lane}: só {cobertura:.1f} avisos certos/min"


def test_the_fix_is_a_measured_improvement_over_what_came_before():
    """A régua contra o comportamento anterior, e não contra um número solto.

    `envelhecer` remonta o caminho antigo peça por peça sobre a mesma
    vigilância — mesmo trajeto, mesmo tremor, mesma semente. O que
    sobra da diferença é o conserto.
    """
    antes = dict((lane, taxa) for lane, taxa, _c in _taxas("antes", NORMAL))
    agora = dict((lane, taxa) for lane, taxa, _c in _taxas("agora", NORMAL))

    for lane in antes:
        assert agora[lane] <= antes[lane] / 2.0, (
            f"{lane}: era {antes[lane]:.1f}%, ficou {agora[lane]:.1f}%"
        )


@pytest.mark.parametrize("tremor", [LEVE, NORMAL, RUIM])
def test_maximum_precision_has_zero_zone_error_in_the_noise_simulation(tremor):
    """O perfil estrito não compra o zero ficando completamente calado.

    O detector é dublado com a posição visual correta: esta régua prova
    a parte espacial (mediana, divisa e nome da zona), não promete que
    qualquer imagem real do jogo possa ser reconhecida sem um corpus.
    """
    for lane, ancora in PERFIS:
        linhas = [
            MEDIR.medir("maxima", lane, ancora, tremor, seed) for seed in SEMENTES
        ]
        assert all(line["estrito"] == 0 for line in linhas), lane
        assert all(line["tolerante"] == 0 for line in linhas), lane
        assert all(line["vaivem"] == 0 for line in linhas), lane
        coverage = sum(line["certas_min"] for line in linhas) / len(linhas)
        assert coverage >= 5.5, f"{lane}: só {coverage:.1f} avisos certos/min"
