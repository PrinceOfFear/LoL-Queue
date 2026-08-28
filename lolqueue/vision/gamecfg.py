"""Ler as opções do jogo que mudam o que a vigilância consegue ver.

Duas interessam. `FlipMiniMap`, ligada, gira o minimapa 180° para a base
do jogador ficar sempre embaixo à esquerda; quem joga de vermelho com ela
ligada vê o mapa de cabeça para baixo, e um aviso que ignore isso manda o
jogador para o lado oposto do mapa — pior que não avisar nada.

`WindowMode` decide se existe imagem para ler. Em tela cheia exclusiva a
placa de vídeo entrega os quadros direto ao monitor, e a captura da área
de trabalho volta preta: o jogador jogou partidas inteiras achando que o
aviso estava quebrado quando, na verdade, o app estava cego. Saber disso
antes do primeiro quadro é o que permite dizer o motivo em vez de emudecer.
"""

from __future__ import annotations

from pathlib import Path

#: Onde o instalador da Riot põe o jogo por padrão no Windows.
DEFAULT_CONFIG = Path(
    r"C:\Riot Games\League of Legends\Config\game.cfg"
)


def read_flag(name: str, path: Path | None = None, default: bool = False) -> bool:
    """Valor de uma chave booleana do game.cfg.

    O arquivo é um INI simples, mas com seções que se repetem e chaves
    que podem simplesmente não existir quando o jogador nunca mexeu na
    opção — nesse caso vale o padrão do jogo. Por isso a leitura é linha
    a linha, sem `configparser`, que morreria numa seção duplicada.
    """
    arquivo = path or DEFAULT_CONFIG
    try:
        texto = arquivo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return default

    alvo = name.lower()
    for linha in texto.splitlines():
        chave, sep, valor = linha.partition("=")
        if sep and chave.strip().lower() == alvo:
            return valor.strip() not in ("0", "", "false", "False")
    return default


def flip_minimap(path: Path | None = None) -> bool:
    """Se o jogador pediu para o minimapa girar junto com o time dele."""
    return read_flag("FlipMiniMap", path)


#: Os valores de `WindowMode` no game.cfg. Só o primeiro cega a captura;
#: "sem bordas" é uma janela em cima de tudo, e o compositor do Windows
#: continua entregando os quadros para quem pede a tela.
EXCLUSIVE_FULLSCREEN = 0
BORDERLESS = 1
WINDOWED = 2


def read_number(name: str, path: Path | None = None) -> int | None:
    """Valor inteiro de uma chave do game.cfg, ou `None` quando não dá.

    "Não dá" cobre três casos que valem o mesmo aqui: arquivo ausente,
    chave ausente e valor que não é número. Em todos, o certo é não
    afirmar nada sobre a opção — inventar um padrão viraria um aviso
    errado na cara do jogador.
    """
    arquivo = path or DEFAULT_CONFIG
    try:
        texto = arquivo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    alvo = name.lower()
    for linha in texto.splitlines():
        chave, sep, valor = linha.partition("=")
        if sep and chave.strip().lower() == alvo:
            try:
                return int(valor.strip())
            except ValueError:
                return None
    return None


def exclusive_fullscreen(path: Path | None = None) -> bool:
    """Se o jogo está no modo de vídeo que cega a captura de tela.

    Só devolve verdadeiro com a leitura confirmando o modo exclusivo.
    Na dúvida — arquivo em outro lugar, chave que o jogador nunca mexeu
    — cala: o preço de um alarme falso é o jogador mexer no vídeo à toa.
    """
    return read_number("WindowMode", path) == EXCLUSIVE_FULLSCREEN
