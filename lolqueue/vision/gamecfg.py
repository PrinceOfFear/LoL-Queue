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

Onde o arquivo está é a parte que já custou uma máquina inteira. Durante
muito tempo havia aqui um caminho fixo na raiz do C:, e num PC que
instalou o jogo em outro disco as duas leituras devolviam o padrão sem
dizer nada: o app não avisava da tela cheia — o aviso que existe
justamente para explicar o silêncio — e ainda tratava o minimapa girado
como normal. Falhava calado, que é o pior jeito de falhar. Agora o lugar
é descoberto como o `lcu.credentials` descobre o lockfile: primeiro
perguntando ao processo do jogo, que sabe de verdade, depois pelos
lugares prováveis. E quem não encontrar nada consegue perguntar, por
`config_path()`, em vez de receber um padrão inventado.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

#: O arquivo, contado a partir da pasta de instalação do jogo.
CONFIG_SUBPATH = Path("Config") / "game.cfg"

#: A pasta que a Riot cria dentro de um disco qualquer.
INSTALL_SUBPATH = Path("Riot Games") / "League of Legends"

#: Os lugares prováveis, para quando o jogo está fechado. A ordem é a da
#: chance de acerto: o instalador propõe a raiz do C:, e quem mudou quase
#: sempre mudou para "Program Files" ou para outro disco — este último
#: cai na varredura de discos, logo abaixo.
CANDIDATE_DIRS = (
    Path(r"C:\Riot Games\League of Legends"),
    Path(r"C:\Program Files\Riot Games\League of Legends"),
    Path(r"C:\Program Files (x86)\Riot Games\League of Legends"),
)

#: Processos que denunciam a instalação, e quantos níveis subir a partir
#: do executável para chegar na raiz dela. O cliente mora na raiz; o jogo
#: em si, numa subpasta `Game`. Perguntar ao processo é o único jeito que
#: acerta uma instalação em pasta escolhida a dedo.
GAME_PROCESSES = {
    "LeagueClientUx.exe": 1,
    "LeagueClient.exe": 1,
    "League of Legends.exe": 2,
}

#: O palpite mais provável, mantido como nome público porque é o que
#: aparece quando é preciso citar um caminho sem ter encontrado nenhum.
DEFAULT_CONFIG = CANDIDATE_DIRS[0] / CONFIG_SUBPATH

#: O caminho já confirmado nesta execução. Só sucesso entra aqui: o jogo
#: pode ter sido instalado — ou aberto — depois da primeira pergunta, e
#: guardar o fracasso condenaria a sessão inteira a não achar mais nada.
_encontrado: Path | None = None


def _from_processes() -> Iterator[Path]:
    """Instalações denunciadas por um processo do jogo em execução."""
    try:
        import psutil
    except Exception:
        return
    try:
        processos = list(psutil.process_iter(["name"]))
    except Exception:
        return
    for proc in processos:
        try:
            nome = proc.info.get("name")
        except Exception:
            continue
        niveis = GAME_PROCESSES.get(nome or "")
        if niveis is None:
            continue
        try:
            raiz = Path(proc.exe())
        except Exception:
            continue
        for _ in range(niveis):
            raiz = raiz.parent
        yield raiz


def _from_drives() -> Iterator[Path]:
    """A pasta da Riot na raiz de cada disco da máquina.

    Cobre o caso comum de quem tem SSD pequeno e joga do D:. Disco de
    rede desconectado pode demorar a responder, mas isto roda uma vez por
    execução e só enquanto o arquivo não foi achado.
    """
    try:
        discos = os.listdrives()
    except (AttributeError, OSError):  # pragma: no cover - fora do Windows
        return
    for disco in discos:
        yield Path(disco) / INSTALL_SUBPATH


def _colher(fonte) -> list[Path]:
    """O que uma fonte de palpites conseguiu dizer, sem deixar erro passar.

    Cada fonte fala com o sistema operacional — lista de processos, lista
    de discos — e qualquer uma pode falhar por permissão, disco de rede
    fora do ar ou política da máquina. Nada disso pode virar exceção no
    caminho de quem só queria ler uma linha de texto: `flip_minimap()` é
    chamado no meio do laço da partida, e uma exceção ali derruba a
    leitura da partida inteira por causa de um palpite que não deu certo.
    """
    try:
        return list(fonte())
    except Exception:
        return []


def installation_dirs() -> Iterator[Path]:
    """Todos os palpites de onde o jogo está, do mais forte ao mais fraco."""
    vistos: set[str] = set()
    palpites = [
        *_colher(_from_processes),
        *CANDIDATE_DIRS,
        *_colher(_from_drives),
    ]
    for pasta in palpites:
        chave = str(pasta).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        yield pasta


def config_path(refresh: bool = False) -> Path | None:
    """O `game.cfg` desta máquina, ou `None` se ele não foi encontrado.

    `None` é resposta útil, não erro: quem chama consegue dizer ao jogador
    que não sabe o modo de vídeo dele, em vez de afirmar um padrão que
    pode estar errado.
    """
    global _encontrado
    if refresh:
        _encontrado = None
    if _encontrado is not None:
        try:
            if _encontrado.is_file():
                return _encontrado
        except OSError:
            pass
        _encontrado = None
    for pasta in installation_dirs():
        arquivo = pasta / CONFIG_SUBPATH
        try:
            if arquivo.is_file():
                _encontrado = arquivo
                return arquivo
        except OSError:
            continue
    return None


def _read_text(path: Path | None) -> str | None:
    arquivo = path or config_path()
    if arquivo is None:
        return None
    try:
        return arquivo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _value_of(name: str, texto: str) -> str | None:
    """O texto à direita do sinal de igual, na primeira linha que casar.

    O arquivo é um INI simples, mas com seções que se repetem e chaves
    que podem simplesmente não existir quando o jogador nunca mexeu na
    opção. Por isso a leitura é linha a linha, sem `configparser`, que
    morreria numa seção duplicada.
    """
    alvo = name.lower()
    for linha in texto.splitlines():
        chave, sep, valor = linha.partition("=")
        if sep and chave.strip().lower() == alvo:
            return valor.strip()
    return None


def read_flag(name: str, path: Path | None = None, default: bool = False) -> bool:
    """Valor de uma chave booleana do game.cfg.

    Arquivo ausente e chave ausente valem o mesmo: o padrão do jogo, que
    é o que o jogador está vendo na tela dele.
    """
    texto = _read_text(path)
    if texto is None:
        return default
    valor = _value_of(name, texto)
    if valor is None:
        return default
    return valor not in ("0", "", "false", "False")


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
    texto = _read_text(path)
    if texto is None:
        return None
    valor = _value_of(name, texto)
    if valor is None:
        return None
    try:
        return int(valor)
    except ValueError:
        return None


def exclusive_fullscreen(path: Path | None = None) -> bool:
    """Se o jogo está no modo de vídeo que cega a captura de tela.

    Só devolve verdadeiro com a leitura confirmando o modo exclusivo.
    Na dúvida — arquivo em outro lugar, chave que o jogador nunca mexeu
    — cala: o preço de um alarme falso é o jogador mexer no vídeo à toa.
    """
    return read_number("WindowMode", path) == EXCLUSIVE_FULLSCREEN
