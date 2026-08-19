"""Runas e feitiços do OP.GG.

A Riot recomenda o que os designers acham bom; o OP.GG mede o que
venceu. Este módulo pega a segunda opinião pelo servidor MCP oficial do
OP.GG — `mcp-api.op.gg`, aberto, sem chave — e devolve as nove runas e
os dois feitiços prontos para o cliente.

**A resposta não é JSON.** É um formato compacto feito para LLM: o
esquema vem declarado em cima, em linhas ``class X: campo,campo``, e os
valores vêm embaixo por posição, ``Runes(8112,8100,"Domination",…)``.
Contar vírgulas seria construir uma bomba-relógio, então o parser aqui
lê o esquema declarado e casa os nomes com os valores. Um campo novo no
meio da lista deixa de ser um incidente.

**Nada aqui é obrigatório.** Toda falha — rede fora, campeão
desconhecido, formato mudado, modo sem dados — vira ``None``, e quem
chama volta para a recomendação da Riot. É a razão de este módulo não
levantar exceção nenhuma para fora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

ENDPOINT = "https://mcp-api.op.gg/mcp"
TOOL = "lol_get_champion_analysis"

#: Faixa de elo consultada. Diamante+ é o corte onde a amostra ainda é
#: grande e as escolhas já são deliberadas.
TIER = "diamond_plus"

#: Sintaxe do próprio servidor: `[]` marca campo de lista. Sem isso ele
#: recusa o pedido e devolve um diagnóstico em vez de dados.
FIELDS = ("data.runes[]", "data.summoner_spells[]")

#: Os dois modos com dados: fila ranqueada e Abismo. Normal e URF
#: existem no servidor mas voltam vazios.
RIFT_MODE = "RANKED"
ARAM_MODE = "ARAM"

#: A posição é obrigatória no pedido, mas no ARAM não muda nada:
#: verificado contra o servidor, as cinco rotas devolvem o mesmo.
ARAM_LANE = "MID"

#: O LCU chama as rotas de um jeito, o OP.GG de outro.
POSITIONS = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "middle": "MID",
    "bottom": "ADC",
    "utility": "SUPPORT",
}

#: Quantas runas o cliente espera: quatro da árvore principal, duas da
#: secundária, três fragmentos.
PERK_COUNT = 9

_CALL = "(?<![A-Za-z0-9_]){name}\\("


@dataclass(frozen=True)
class Build:
    """O que o cliente precisa para montar uma página e os feitiços."""

    style: int
    sub_style: int
    perks: tuple[int, ...]
    spells: tuple[int, int]


# ---------- o formato compacto ----------


def _split(text: str) -> list[str]:
    """Quebra a lista de argumentos no nível de fora.

    Vírgula dentro de aspas, de colchete ou de parêntese pertence ao
    valor, não à separação — nome de runa com vírgula existe.
    """
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(text):
        if quoted:
            if char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def _arguments(text: str, name: str) -> str | None:
    """Conteúdo entre parênteses da primeira chamada a `name`."""
    match = re.search(_CALL.format(name=name), text)
    if match is None:
        return None
    depth = 0
    quoted = False
    for index in range(match.end() - 1, len(text)):
        char = text[index]
        if quoted:
            if char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[match.end() : index]
    return None


def _fields(text: str, name: str) -> dict[str, str] | None:
    """Casa o esquema declarado com os valores, por nome."""
    match = re.search(rf"^class {name}: *(.+)$", text, re.MULTILINE)
    if match is None:
        return None
    names = [field.strip() for field in match.group(1).split(",")]
    values = _arguments(text, name)
    if values is None:
        return None
    parts = _split(values)
    if len(parts) != len(names):
        return None
    return dict(zip(names, parts))


def _int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ints(value: str) -> list[int] | None:
    """Lê `[1,2,3]`. Qualquer coisa que não seja inteiro invalida tudo."""
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    inner = text[1:-1].strip()
    if not inner:
        return []
    numbers = [_int(part) for part in _split(inner)]
    if any(number is None for number in numbers):
        return None
    return numbers  # type: ignore[return-value]


def parse_build(text: str) -> Build | None:
    """Lê a resposta do OP.GG. Devolve ``None`` se faltar qualquer peça.

    Meia recomendação é pior que nenhuma: entrar em partida com três
    runas certas e o resto em branco é um estrago silencioso. Por isso
    tudo aqui é tudo-ou-nada.
    """
    runes = _fields(text, "Runes")
    spells = _fields(text, "SummonerSpells")
    if runes is None or spells is None:
        return None

    style = _int(runes.get("primary_page_id", ""))
    sub_style = _int(runes.get("secondary_page_id", ""))
    primary = _ints(runes.get("primary_rune_ids", ""))
    secondary = _ints(runes.get("secondary_rune_ids", ""))
    shards = _ints(runes.get("stat_mod_ids", ""))
    chosen = _ints(spells.get("ids", ""))

    if style is None or sub_style is None:
        return None
    if primary is None or secondary is None or shards is None:
        return None
    if chosen is None or len(chosen) < 2:
        return None

    perks = tuple(primary + secondary + shards)
    if len(perks) != PERK_COUNT:
        return None

    return Build(
        style=style,
        sub_style=sub_style,
        perks=perks,
        spells=(chosen[0], chosen[1]),
    )


# ---------- a ida à rede ----------


def _send(arguments: dict) -> str:
    """Chama a ferramenta MCP e devolve o texto da resposta.

    O servidor fala JSON-RPC e pode responder tanto em JSON puro quanto
    em `text/event-stream`; as duas formas passam por aqui.
    """
    import json

    import requests

    response = requests.post(
        ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": arguments},
        },
        timeout=10,
    )
    response.raise_for_status()

    body = response.text
    for line in body.splitlines():
        if line.startswith("data: "):
            body = line[6:]
            break
    payload = json.loads(body)
    content = (payload.get("result") or {}).get("content") or []
    return "".join(part.get("text", "") for part in content)


class OpggSource:
    """Busca a recomendação do OP.GG, com memória do que já perguntou.

    O cache vale enquanto o app estiver aberto. Não é otimização de
    rede: é para o mesmo campeão na mesma rota não custar segundos de
    novo numa seleção seguinte.
    """

    def __init__(self, send: Callable[[dict], str] | None = None) -> None:
        self._send = send or _send
        self._cache: dict[tuple[str, str], Build] = {}

    def fetch(self, champion: str, position: str | None, aram: bool) -> Build | None:
        """Runas e feitiços para este campeão nesta rota, ou ``None``.

        Na Fenda, sem rota não há pergunta a fazer: o OP.GG exige a
        posição, e no modo cego o cliente não atribui nenhuma. No
        Abismo é o contrário — ninguém tem rota, e o servidor devolve
        a mesma resposta para todas elas, então qualquer uma serve
        para satisfazer o campo obrigatório.
        """
        if not champion:
            return None

        if aram:
            mode, lane, key = ARAM_MODE, ARAM_LANE, (champion, ARAM_MODE)
        else:
            lane = POSITIONS.get((position or "").lower())
            if lane is None:
                return None
            mode, key = RIFT_MODE, (champion, lane)
        if key in self._cache:
            return self._cache[key]

        try:
            text = self._send(
                {
                    "champion": champion,
                    "position": lane,
                    "game_mode": mode,
                    "tier": TIER,
                    "lang": "en_US",
                    "desired_output_fields": list(FIELDS),
                }
            )
        except Exception:
            # A rede é o caminho normal de falha aqui, e falhar é
            # aceitável: quem chama tem a Riot de reserva. Guardar o
            # erro no cache seria condenar a sessão inteira.
            return None

        build = parse_build(text or "")
        if build is not None:
            self._cache[key] = build
        return build
