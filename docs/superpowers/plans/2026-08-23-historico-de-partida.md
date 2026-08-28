# Histórico de Partida — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nova página "Histórico" na barra lateral que mostra nick#tag,
nível, elo por fila e as últimas 10 partidas (campeão, resultado, KDA,
CS, duração, modo, tempo relativo) do invocador conectado, puxando os
dados do servidor MCP público do OP.GG já usado pelo app.

**Architecture:** Extrai o parser do formato compacto do MCP (hoje só
em `core/opgg.py`) para `core/mcp_format.py`, compartilhado por
`core/opgg.py` (build de campeão) e o novo `core/summoner_history.py`
(perfil + partidas). Um novo `core/identity.py` lê da LCU quem está
jogando (nome, tag, região). Um `QThread` (`ui/history_loader.py`)
encadeia os dois: identidade → OP.GG. A página (`ui/pages/history.py`)
segue o padrão de vazio/conteúdo de `AnalysisPage`. `window.py` monta a
fiação, igual já faz para análise e confronto.

**Tech Stack:** Python 3.13+, PySide6 (Qt), `requests`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-historico-de-partida-design.md`

## Global Constraints

- Sem cache em `SummonerHistorySource` — histórico envelhece rápido
  (ao contrário de `OpggSource`, que cacheia build de campeão).
- Nenhuma imagem remota (ícone de perfil do OP.GG) é baixada — só
  texto no cabeçalho. Retrato de partida reaproveita o cache de ícones
  de campeão já existente (por id, via LCU), como `AnalysisPage` já faz.
- Qualquer falha (rede, campo faltando, formato mudado, cliente
  fechado) vira `None`/`()` — nunca uma exceção para quem chama.
- Uma consulta por vez; sem polling, sem tempo real. Disparada ao abrir
  a página e por um botão "Atualizar".
- `opgg.py` deve continuar passando `tests/test_opgg.py` inalterado
  após o refactor (só `Build`, `OpggSource`, `parse_build` são API
  pública testada).
- Fora de escopo (não implementar): detalhe de uma partida (10
  participantes), busca de outro invocador, atualização automática em
  tempo real, gráfico de progresso de elo.

---

## Task 1: Extrair `core/mcp_format.py` de `core/opgg.py`

Refactor puro — comportamento idêntico, verificado pela suite já
existente. `opgg.py` fica menor e sem repetir infraestrutura para a
nova fonte de dados.

**Files:**
- Create: `lolqueue/core/mcp_format.py`
- Modify: `lolqueue/core/opgg.py`
- Test: `tests/test_opgg.py` (já existe, não muda — é a rede de
  segurança deste refactor)

**Interfaces:**
- Produces (para Task 4 usar): `mcp_format.schema(text) -> dict[str, list[str]]`,
  `mcp_format.unpack(value, schema) -> dict[str, str] | None`,
  `mcp_format.entries(value) -> list[str]`,
  `mcp_format.first(value) -> str | None`,
  `mcp_format.root_data(text, schema, root) -> dict[str, str] | None`,
  `mcp_format.to_int(value) -> int | None`,
  `mcp_format.to_ints(value) -> list[int] | None`,
  `mcp_format.to_strings(value) -> list[str]`,
  `mcp_format.to_float(value) -> float | None`,
  `mcp_format.split(text) -> list[str]`,
  `mcp_format.call_arguments(text, name) -> str | None`,
  `mcp_format.send_tool(endpoint, tool, arguments) -> str`.

- [ ] **Step 1: Rodar a suite antes de tocar em nada, para ter uma linha de base**

Run: `py -m pytest tests/test_opgg.py -q`
Expected: PASS (todos os testes já existentes)

- [ ] **Step 2: Criar `lolqueue/core/mcp_format.py`**

```python
"""Formato compacto de resposta do MCP do OP.GG.

Não é JSON: o esquema vem declarado em cima, em linhas ``class X:
campo,campo``, e os valores vêm embaixo por posição,
``Nome(valor,valor,...)``. Este módulo lê essa estrutura pelo nome do
campo declarado, nunca pela posição ou pelo nome da classe — o próprio
servidor reaproveita o mesmo nome de classe para coisas diferentes
(``CoreItems`` serve para itens iniciais, botas e até feitiços).

Compartilhado por `core/opgg.py` (build de campeão) e
`core/summoner_history.py` (perfil e histórico de partidas): as duas
fontes chamam o mesmo servidor MCP e recebem o mesmo formato — só muda
a ferramenta e os campos pedidos.
"""

from __future__ import annotations

import json
import re

_CALL = "(?<![A-Za-z0-9_]){name}\\("
_NAMED = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$", re.DOTALL)


def split(text: str) -> list[str]:
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


def call_arguments(text: str, name: str) -> str | None:
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


def schema(text: str) -> dict[str, list[str]]:
    """As linhas ``class X: campo,campo`` que abrem a resposta."""
    found: dict[str, list[str]] = {}
    for name, fields in re.findall(r"^class (\w+): *(.+)$", text, re.MULTILINE):
        found.setdefault(name, [field.strip() for field in fields.split(",")])
    return found


def unpack(value: str | None, schema: dict[str, list[str]]) -> dict[str, str] | None:
    """Abre um ``Nome(...)`` casando cada valor com o campo declarado.

    Recusa o que não bater: classe desconhecida ou quantidade de valores
    diferente da que o esquema anuncia. Nesse ponto já não dá para saber
    qual valor é qual, e chutar sairia caro.
    """
    if value is None:
        return None
    match = _NAMED.match(value.strip())
    if match is None:
        return None
    fields = schema.get(match.group(1))
    if fields is None:
        return None
    parts = split(match.group(2))
    if len(parts) != len(fields):
        return None
    return dict(zip(fields, parts))


def entries(value: str) -> list[str]:
    """Os elementos de ``[A(…),B(…)]``; fora de lista, o próprio valor.

    O servidor usa lista sempre que há mais de uma opção, e valor solto
    quando há uma só. Aqui os dois casos viram a mesma coisa.
    """
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return [text]
    inner = text[1:-1].strip()
    return split(inner) if inner else []


def first(value: str | None) -> str | None:
    """A primeira opção, quando o servidor manda uma lista delas."""
    if value is None:
        return None
    found = entries(value)
    return found[0] if found else None


def root_data(text: str, schema: dict[str, list[str]], root: str) -> dict[str, str] | None:
    """O bloco ``Data(...)`` de dentro da chamada raiz (`root`), campo a campo.

    `root` é o nome da classe que embrulha a resposta inteira — muda
    por ferramenta (`LolGetChampionAnalysis`, `LolGetSummonerProfile`,
    `LolListSummonerMatches`, ...), mas a estrutura é sempre a mesma:
    ``Root(Data(...))``.
    """
    fields = schema.get(root)
    values = call_arguments(text, root)
    if fields is None or values is None:
        return None
    parts = split(values)
    if len(parts) != len(fields):
        return None
    return unpack(dict(zip(fields, parts)).get("data"), schema)


def to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_ints(value: str) -> list[int] | None:
    """Lê `[1,2,3]`. Qualquer coisa que não seja inteiro invalida tudo."""
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    inner = text[1:-1].strip()
    if not inner:
        return []
    numbers = [to_int(part) for part in split(inner)]
    if any(number is None for number in numbers):
        return None
    return numbers  # type: ignore[return-value]


def to_strings(value: str) -> list[str]:
    """Lê uma lista de textos entre aspas, tipo `["Malignance","Void Staff"]`."""
    text = value.strip()
    if not text:
        return []
    return [entry.strip().strip('"') for entry in entries(text)]


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def send_tool(endpoint: str, tool: str, arguments: dict) -> str:
    """Chama uma ferramenta MCP e devolve o texto da resposta.

    O servidor fala JSON-RPC e pode responder tanto em JSON puro quanto
    em `text/event-stream`; as duas formas passam por aqui.
    """
    import requests

    response = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
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
```

- [ ] **Step 3: Rodar a suite de novo — `mcp_format.py` ainda não é usado por ninguém, nada deve mudar**

Run: `py -m pytest tests/test_opgg.py -q`
Expected: PASS (idêntico ao Step 1)

- [ ] **Step 4: Reescrever `lolqueue/core/opgg.py` para importar de `mcp_format`**

Substituir o arquivo inteiro por esta versão (mesmas docstrings e
comentários; as funções `_split`, `_arguments`, `_schema`, `_unpack`,
`_entries`, `_first`, `_data`, `_int`, `_ints`, `_strings`, `_float`
saem daqui, e `_send` passa a delegar):

```python
"""Runas, feitiços e itens do OP.GG.

A Riot recomenda o que os designers acham bom; o OP.GG mede o que
venceu. Este módulo pega a segunda opinião pelo servidor MCP oficial do
OP.GG — `mcp-api.op.gg`, aberto, sem chave — e devolve as nove runas,
os dois feitiços e os blocos de itens prontos para o cliente.

O formato de resposta (compacto, não-JSON) é lido por
`core/mcp_format.py`, compartilhado com `core/summoner_history.py`.

**Nada aqui é obrigatório.** Toda falha — rede fora, campeão
desconhecido, formato mudado, modo sem dados — vira ``None``, e quem
chama volta para a recomendação da Riot. É a razão de este módulo não
levantar exceção nenhuma para fora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import mcp_format

ENDPOINT = "https://mcp-api.op.gg/mcp"
TOOL = "lol_get_champion_analysis"

#: Faixa de elo consultada. Diamante+ é o corte onde a amostra ainda é
#: grande e as escolhas já são deliberadas.
TIER = "diamond_plus"

#: Sintaxe do próprio servidor: `[]` marca campo de lista. Sem isso ele
#: recusa o pedido e devolve um diagnóstico em vez de dados.
#:
#: As sinergias vêm por rota, e as rotas disponíveis mudam conforme a
#: posição do campeão: um meio recebe `jungle`, `adc` e `support`, e
#: `mid` é recusado — ele não faz dupla consigo mesmo. Pedir as cinco e
#: deixar o servidor descartar o que não se aplica é mais simples do que
#: manter aqui uma tabela de quem combina com quem; o descarte é
#: gracioso, vem anotado em `_field_diagnostics` e não atrapalha o
#: resto da resposta.
FIELDS = (
    "data.runes[]",
    "data.summoner_spells[]",
    "data.starter_items[]",
    "data.boots[]",
    "data.core_items[]",
    "data.fourth_items[]",
    "data.fifth_items[]",
    "data.sixth_items[]",
    "data.last_items[]",
    "data.skills[]",
    "data.skill_masteries[]",
    "data.strong_counters[]",
    "data.weak_counters[]",
    "data.synergies.top[]",
    "data.synergies.jungle[]",
    "data.synergies.mid[]",
    "data.synergies.adc[]",
    "data.synergies.support[]",
    "data.summary.average_stats",
    "data.damage_type",
)

#: Os blocos do arsenal, na ordem em que se compra. O rótulo é o que
#: aparece na loja, dentro da partida.
ITEM_BLOCKS = (
    ("starter_items", "Iniciais"),
    ("boots", "Botas"),
    ("core_items", "Principais"),
    ("fourth_items", "4º item"),
    ("fifth_items", "5º item"),
    ("sixth_items", "6º item"),
    ("last_items", "Último item"),
)

#: Os campos que formam o build inteiro, iguais em toda página. Os
#: outros são escolhas entre alternativas, e cada uma vira uma página.
#: Quem separa os dois grupos é esta lista, não quantas alternativas o
#: OP.GG mandou: um slot situacional com uma opção só continua sendo
#: situacional, e tem que ficar no lugar dele na ordem da loja.
CORE_FIELDS = frozenset({"starter_items", "boots", "core_items"})

#: O rótulo do bloco que junta os slots do quarto item em diante. Eles
#: chegam separados do OP.GG e vão juntos para a loja, na ordem de
#: compra: ver `_pages`.
SITUATIONAL_LABEL = "Situacionais"

#: Os dois critérios que os dados sustentam, e que dão nome às páginas.
#: O OP.GG mede cada slot por uso e por vitória, então estas duas
#: leituras existem de verdade; uma terceira aba seria numeração sem
#: dizer o que muda entre uma e outra.
MOST_PLAYED_LABEL = "Mais jogada"
BEST_RATE_LABEL = "Maior taxa"

#: Amostra mínima para um item disputar a página da maior taxa. Sem
#: piso, um slot de três partidas elege o que venceu a única que jogou
#: — foi assim que "Banshee's Veil — 100% de vitórias" virou
#: recomendação principal. Quando nenhum item do slot alcança o piso,
#: o slot repete o mais jogado; se isso acontecer em todos, as duas
#: páginas coincidem e o arsenal sai com uma aba só, que é a resposta
#: honesta para dado insuficiente.
MIN_SAMPLE = 30

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

#: A chamada que embrulha a resposta inteira.
ROOT = "LolGetChampionAnalysis"


@dataclass(frozen=True)
class Block:
    """Um bloco do arsenal: o rótulo na loja e o que comprar nele.

    `games` é o tamanho da amostra que mediu este bloco, e existe para
    ordenar alternativas. Sem ele a ordem sairia por taxa de vitória
    pura, e um item de três partidas com 100% passaria na frente do que
    todo mundo compra — conselho fabricado a partir de ruído.
    """

    label: str
    items: tuple[int, ...]
    win_rate: float
    games: int = 0


@dataclass(frozen=True)
class Page:
    """Uma página do arsenal: por que ela existe, e o que comprar nela.

    `label` é o critério que a montou, e vai para o título do conjunto
    na loja — é ele que distingue uma aba da outra durante a partida.
    Fica vazio quando só há uma página: aí não existe escolha a
    sinalizar, e o rótulo seria ruído no nome da aba.
    """

    label: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Counter:
    """Um confronto medido: quanto o nosso campeão venceu contra aquele.

    `win_rate` é sempre a taxa do **nosso** campeão, nunca a do outro.
    O servidor manda as duas, e ainda um terceiro campo `win_rate` que
    troca de dono conforme a lista — vale a do adversário quando ele é
    quem vence. Guardar sempre o mesmo lado é o que deixa as duas
    listas comparáveis na tela.
    """

    champion_id: int
    champion: str
    win_rate: float
    games: int


@dataclass(frozen=True)
class Synergy:
    """Um campeão que costuma vencer junto com o nosso, e em que rota."""

    champion_id: int
    champion: str
    position: str
    win_rate: float
    games: int


@dataclass(frozen=True)
class Stats:
    """O boletim do campeão no elo consultado.

    `tier` e `rank` são a nota do OP.GG: tier 1 é o topo, e `rank` é a
    colocação entre todos os campeões da rota.
    """

    games: int
    win_rate: float
    pick_rate: float
    ban_rate: float
    kda: float
    tier: int
    rank: int


@dataclass(frozen=True)
class Build:
    """O que o cliente precisa para montar página, feitiços e arsenal.

    `pages` é uma página de arsenal por critério de leitura: a build
    mais jogada e a de maior taxa de vitória. Cada slot situacional é
    resolvido pelo ranking que o OP.GG já mede — nunca por uma
    combinação que ele não tenha medido.

    Do `skill_order` para baixo é tudo material de leitura: nada disso
    o cliente sabe aplicar sozinho. A ordem de habilidade, em especial,
    não tem endpoint no LCU — dá para mostrar, não para montar. Por
    isso esses campos são opcionais e falham para vazio, enquanto runas
    e feitiços continuam sendo tudo-ou-nada: perder a grade de counters
    não estraga uma partida, entrar com meia página de runas estraga.
    """

    style: int
    sub_style: int
    perks: tuple[int, ...]
    spells: tuple[int, int]
    pages: tuple[Page, ...] = ()
    skill_order: tuple[str, ...] = ()
    skill_max: tuple[str, ...] = ()
    strong_against: tuple[Counter, ...] = ()
    weak_against: tuple[Counter, ...] = ()
    synergies: tuple[Synergy, ...] = ()
    stats: Stats | None = None
    damage_type: str = ""


def _letters(value: str) -> tuple[str, ...]:
    """A sequência de habilidades, `["Q","E","W"]`, já sem as aspas.

    Só passa o que de fato nomeia uma habilidade. O campo é desenhado
    na tela como letra, e um valor estranho vindo do servidor viraria
    um quadradinho vazio no meio da ordem em vez de um erro visível.
    """
    letters = tuple(entry.upper() for entry in mcp_format.to_strings(value))
    if not letters or any(letter not in ("Q", "W", "E", "R") for letter in letters):
        return ()
    return letters


def _counters(value: str | None, schema: dict[str, list[str]]) -> tuple[Counter, ...]:
    """Uma das duas listas de confronto, a favor ou contra.

    O servidor etiqueta as duas como `StrongCounter`; quem diz qual é
    qual é a posição em `Data`, não o nome. Aqui as duas passam pela
    mesma leitura, e o sentido vem de quem chamou.
    """
    if value is None:
        return ()
    found: list[Counter] = []
    for entry in mcp_format.entries(value):
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        champion_id = mcp_format.to_int(fields.get("champion_id", ""))
        name = fields.get("champion_name", "").strip().strip('"')
        rate = mcp_format.to_float(fields.get("my_win_rate", ""))
        if champion_id is None or not name or rate is None:
            continue
        found.append(
            Counter(
                champion_id=champion_id,
                champion=name,
                win_rate=rate,
                games=mcp_format.to_int(fields.get("play", "")) or 0,
            )
        )
    return tuple(found)


def _synergies(value: str | None, schema: dict[str, list[str]]) -> tuple[Synergy, ...]:
    """As duplas que vencem junto, de todas as rotas que vieram.

    O servidor agrupa por rota e o agrupamento muda conforme a posição
    do campeão. Em vez de confiar no nome do grupo, cada entrada diz a
    própria rota em `synergy_position` — então dá para achatar tudo
    numa lista só e continuar sabendo quem joga onde.
    """
    if value is None:
        return ()
    groups = mcp_format.unpack(value, schema)
    if groups is None:
        return ()
    found: list[Synergy] = []
    for lane in groups.values():
        for entry in mcp_format.entries(lane):
            fields = mcp_format.unpack(entry, schema)
            if fields is None:
                continue
            champion_id = mcp_format.to_int(fields.get("synergy_champion_id", ""))
            name = fields.get("synergy_champion_name", "").strip().strip('"')
            rate = mcp_format.to_float(fields.get("win_rate", ""))
            if champion_id is None or not name or rate is None:
                continue
            found.append(
                Synergy(
                    champion_id=champion_id,
                    champion=name,
                    position=fields.get("synergy_position", "").strip().strip('"'),
                    win_rate=rate,
                    games=mcp_format.to_int(fields.get("play", "")) or 0,
                )
            )
    return tuple(found)


def _stats(value: str | None, schema: dict[str, list[str]]) -> Stats | None:
    """O boletim, que chega embrulhado num `Summary`."""
    summary = mcp_format.unpack(value, schema)
    if summary is None:
        return None
    fields = mcp_format.unpack(summary.get("average_stats"), schema)
    if fields is None:
        return None
    games = mcp_format.to_int(fields.get("play", ""))
    win_rate = mcp_format.to_float(fields.get("win_rate", ""))
    if games is None or win_rate is None:
        return None
    return Stats(
        games=games,
        win_rate=win_rate,
        pick_rate=mcp_format.to_float(fields.get("pick_rate", "")) or 0.0,
        ban_rate=mcp_format.to_float(fields.get("ban_rate", "")) or 0.0,
        kda=mcp_format.to_float(fields.get("kda", "")) or 0.0,
        tier=mcp_format.to_int(fields.get("tier", "")) or 0,
        rank=mcp_format.to_int(fields.get("rank", "")) or 0,
    )


def _field_options(
    entries: list[str], label: str, schema: dict[str, list[str]]
) -> list[Block]:
    """As alternativas de um campo, cada uma como o seu próprio bloco.

    A etiqueta é a do campo, sem o nome do item junto. Houve aqui um
    `named` que produzia "4º item: Zhonya's Hourglass" para distinguir
    uma aba da outra; desde que os slots situacionais passaram a ir num
    bloco só, `_pages` descarta essa etiqueta e monta a sua própria.
    """
    options: list[Block] = []
    for entry in entries:
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        ids = mcp_format.to_ints(fields.get("ids", ""))
        if not ids:
            continue
        play = mcp_format.to_int(fields.get("play", "")) or 0
        win = mcp_format.to_int(fields.get("win", "")) or 0
        options.append(
            Block(
                label=label,
                items=tuple(ids),
                win_rate=win / play if play else 0.0,
                games=play,
            )
        )
    return options


def _slot_choice(options: list[Block], by_rate: bool) -> Block:
    """A opção deste slot para uma das duas páginas.

    `options` chega ordenado por amostra, então o mais jogado é o
    primeiro. Para a página da maior taxa só concorre quem passou de
    `MIN_SAMPLE`; se ninguém passou, o slot repete o mais jogado em vez
    de eleger o campeão de três partidas.
    """
    if not by_rate:
        return options[0]
    solid = [block for block in options if block.games >= MIN_SAMPLE]
    if not solid:
        return options[0]
    return max(solid, key=lambda block: (block.win_rate, block.games))


def _situational(chosen: list[Block], core=()) -> tuple[int, ...]:
    """Os slots situacionais na ordem de compra, sem item repetido.

    Um mesmo item pode encabeçar dois slots — o OP.GG mede cada um por
    conta, e Zhonya's lidera tanto o 4º quanto o 6º. Em blocos
    separados isso só parecia estranho; numa lista de compra única
    viraria "compre Zhonya's duas vezes", que o jogo não permite.

    `core` é o que os blocos anteriores já mandaram comprar, e sai
    daqui pelo mesmo motivo. A estatística de "6º item" conta também
    quem montou o núcleo tarde, então o OP.GG devolve Malignance como
    sexto item da Annie — que é o primeiro item dela. Na loja isso
    apareceria como o mesmo lendário em dois blocos.
    """
    items: list[int] = list(core)
    guarded = len(items)
    for block in chosen:
        items.extend(item for item in block.items if item not in items)
    return tuple(items[guarded:])


def _pages(data: dict[str, str], schema: dict[str, list[str]]) -> tuple[Page, ...]:
    """Monta as páginas do arsenal com o que veio na resposta.

    Item é enfeite: se um campo faltar ou vier vazio, ele some e o
    resto segue. `starter_items`, `boots` e `core_items` chegam como um
    valor só — o núcleo do build, igual em toda página.

    **Os slots finais viram um bloco só.** Do quarto item em diante o
    OP.GG manda alternativas por slot, e havia aqui um bloco por slot:
    a loja ficava com "4º item", "5º item", "6º item" e "Último item"
    lado a lado, cada um com um único item dentro. Ler aquilo durante a
    partida era catar item em quatro títulos separados. Agora a
    sequência inteira vai num bloco `SITUATIONAL_LABEL`, na ordem em
    que se compra, como fazem os outros apps do gênero.

    **As páginas são critérios, não posições.** Havia aqui uma página
    por alternativa — a primeira com a melhor de cada slot, a segunda
    com a seguinte —, e o número da aba não dizia o que mudava dentro
    dela. Agora são duas leituras do mesmo dado, cada uma com nome: a
    build mais jogada e a de maior taxa. Quando as duas dão no mesmo
    conjunto, sai uma aba só, sem rótulo — não havia escolha a
    oferecer.
    """
    core: list[Block] = []
    situational: list[list[Block]] = []
    for field, label in ITEM_BLOCKS:
        raw = data.get(field)
        if raw is None:
            continue
        is_core = field in CORE_FIELDS
        options = _field_options(mcp_format.entries(raw), label, schema)
        if not options:
            continue
        if is_core:
            core.append(options[0])
        else:
            options.sort(key=lambda block: (block.games, block.win_rate), reverse=True)
            situational.append(options)

    if not situational:
        if not core:
            return ()
        return (Page(label="", blocks=tuple(core)),)

    # O que o núcleo já compra não volta na lista situacional.
    comprado = tuple(item for block in core for item in block.items)

    pages: list[Page] = []
    seen: set[frozenset[int]] = set()
    for label, by_rate in ((MOST_PLAYED_LABEL, False), (BEST_RATE_LABEL, True)):
        items = _situational(
            [_slot_choice(o, by_rate) for o in situational], comprado
        )
        if not items:
            continue
        assinatura = frozenset(items)
        if assinatura in seen:
            continue
        seen.add(assinatura)
        pages.append(
            Page(
                label=label,
                blocks=tuple(core)
                + (
                    Block(
                        label=SITUATIONAL_LABEL,
                        items=items,
                        # Taxa e amostra ficam de fora: são de cada item,
                        # e estampar a de um só no título do bloco inteiro
                        # daria a entender que vale para todos.
                        win_rate=0.0,
                        games=0,
                    ),
                ),
            )
        )

    if len(pages) == 1:
        # Critério só nomeia o que se contrapõe a outro. Sozinho na
        # loja, "Mais jogada" sugeriria uma segunda aba que não existe.
        pages = [Page(label="", blocks=pages[0].blocks)]
    return tuple(pages)


def parse_build(text: str) -> Build | None:
    """Lê a resposta do OP.GG. Devolve ``None`` se faltar runa ou feitiço.

    Meia recomendação é pior que nenhuma: entrar em partida com três
    runas certas e o resto em branco é um estrago silencioso. Por isso
    a página é tudo-ou-nada. Os itens seguem regra própria, mais frouxa,
    porque um bloco a menos na loja não estraga nada.
    """
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, ROOT)
    if data is None:
        return None

    runes = mcp_format.unpack(mcp_format.first(data.get("runes")), schema)
    spells = mcp_format.unpack(mcp_format.first(data.get("summoner_spells")), schema)
    if runes is None or spells is None:
        return None

    style = mcp_format.to_int(runes.get("primary_page_id", ""))
    sub_style = mcp_format.to_int(runes.get("secondary_page_id", ""))
    primary = mcp_format.to_ints(runes.get("primary_rune_ids", ""))
    secondary = mcp_format.to_ints(runes.get("secondary_rune_ids", ""))
    shards = mcp_format.to_ints(runes.get("stat_mod_ids", ""))
    chosen = mcp_format.to_ints(spells.get("ids", ""))

    if style is None or sub_style is None:
        return None
    if primary is None or secondary is None or shards is None:
        return None
    if chosen is None or len(chosen) < 2:
        return None

    perks = tuple(primary + secondary + shards)
    if len(perks) != PERK_COUNT:
        return None

    skills = mcp_format.unpack(mcp_format.first(data.get("skills")), schema)
    masteries = mcp_format.unpack(mcp_format.first(data.get("skill_masteries")), schema)

    return Build(
        style=style,
        sub_style=sub_style,
        perks=perks,
        spells=(chosen[0], chosen[1]),
        pages=_pages(data, schema),
        skill_order=_letters(skills.get("order", "")) if skills else (),
        skill_max=_letters(masteries.get("ids", "")) if masteries else (),
        strong_against=_counters(data.get("strong_counters"), schema),
        weak_against=_counters(data.get("weak_counters"), schema),
        synergies=_synergies(data.get("synergies"), schema),
        stats=_stats(data.get("summary"), schema),
        damage_type=(data.get("damage_type") or "").strip().strip('"'),
    )


def _send(arguments: dict) -> str:
    """Chama a ferramenta de análise de campeão e devolve o texto da resposta."""
    return mcp_format.send_tool(ENDPOINT, TOOL, arguments)


class OpggSource:
    """Busca a recomendação do OP.GG, com memória do que já perguntou.

    O cache vale enquanto o app estiver aberto. Não é otimização de
    rede: é para o mesmo campeão na mesma rota não custar segundos de
    novo numa seleção seguinte.
    """

    def __init__(self, send: Callable[[dict], str] | None = None) -> None:
        self._send = send or _send
        self._cache: dict[tuple[str, str, str], Build] = {}

    def fetch(
        self, champion: str, position: str | None, aram: bool, tier: str = TIER
    ) -> Build | None:
        """Runas, feitiços e itens deste campeão nesta rota, ou ``None``.

        Na Fenda, sem rota não há pergunta a fazer: o OP.GG exige a
        posição, e no modo cego o cliente não atribui nenhuma. No
        Abismo é o contrário — ninguém tem rota, e o servidor devolve
        a mesma resposta para todas elas, então qualquer uma serve
        para satisfazer o campo obrigatório.

        `tier` é o elo escolhido nos ajustes — o cache entra por ele
        também, senão trocar o elo em pleno app continuaria devolvendo
        a build do elo anterior para um campeão já perguntado.
        """
        if not champion:
            return None

        if aram:
            mode, lane, key = ARAM_MODE, ARAM_LANE, (champion, ARAM_MODE, tier)
        else:
            lane = POSITIONS.get((position or "").lower())
            if lane is None:
                return None
            mode, key = RIFT_MODE, (champion, lane, tier)
        if key in self._cache:
            return self._cache[key]

        try:
            text = self._send(
                {
                    "champion": champion,
                    "position": lane,
                    "game_mode": mode,
                    "tier": tier,
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
```

- [ ] **Step 5: Rodar a suite completa de `opgg` de novo — comportamento tem que ser idêntico**

Run: `py -m pytest tests/test_opgg.py -q`
Expected: PASS (mesmos testes, mesmo resultado dos Steps 1 e 3)

- [ ] **Step 6: Rodar a suite inteira do projeto, para garantir que nada mais importa símbolos removidos**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add lolqueue/core/mcp_format.py lolqueue/core/opgg.py
git commit -m "refactor: extrai parser do MCP para core/mcp_format.py"
```

---

## Task 2: `RIOT_REGION_LOCALE` em `lcu/endpoints.py`

**Files:**
- Modify: `lolqueue/lcu/endpoints.py:27`

**Interfaces:**
- Produces: `endpoints.RIOT_REGION_LOCALE: str` (usado por Task 3).

- [ ] **Step 1: Adicionar a constante logo após `CURRENT_SUMMONER`**

Em `lolqueue/lcu/endpoints.py`, depois da linha `CURRENT_SUMMONER = "/lol-summoner/v1/current-summoner"`:

```python
CURRENT_SUMMONER = "/lol-summoner/v1/current-summoner"
#: Rota do Riot Client (não do LCU), servida pela mesma conexão. O
#: campo `region` vem em maiúsculas ("BR", "KR", "EUNE") — exatamente
#: o formato que o MCP do OP.GG pede para identificar o servidor.
RIOT_REGION_LOCALE = "/riotclient/region-locale"
```

- [ ] **Step 2: Conferir que nada quebrou (constante nova, ninguém usa ainda)**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add lolqueue/lcu/endpoints.py
git commit -m "feat: adiciona rota RIOT_REGION_LOCALE"
```

---

## Task 3: `core/identity.py`

Quem está jogando, segundo o cliente aberto — junta dois endpoints da
LCU que sozinhos não bastam.

**Files:**
- Create: `lolqueue/core/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `endpoints.CURRENT_SUMMONER`, `endpoints.RIOT_REGION_LOCALE`
  (Task 2); `LcuError` de `lolqueue.lcu.client`.
- Produces (para Task 6 usar): `Identity(game_name: str, tag_line: str,
  region: str, level: int)`; `current_identity(client) -> Identity | None`.

- [ ] **Step 1: Escrever `tests/test_identity.py` (falha: módulo não existe)**

```python
"""Quem está jogando, segundo o cliente — ou None quando falta algo."""

from lolqueue.core.identity import Identity, current_identity
from lolqueue.lcu.client import LcuError
from lolqueue.lcu.endpoints import CURRENT_SUMMONER, RIOT_REGION_LOCALE

_MISSING = object()


class FakeClient:
    """Devolve uma resposta fixa por rota, ou levanta o que for pedido."""

    def __init__(self, responses: dict):
        self._responses = responses

    def get(self, path):
        value = self._responses.get(path, _MISSING)
        if value is _MISSING:
            raise LcuError(f"rota não configurada no fake: {path}")
        if isinstance(value, Exception):
            raise value
        return value


def test_a_full_response_becomes_an_identity():
    client = FakeClient(
        {
            CURRENT_SUMMONER: {
                "gameName": "Jogador",
                "tagLine": "BR1",
                "summonerLevel": 1098,
            },
            RIOT_REGION_LOCALE: {"region": "BR", "locale": "pt_BR"},
        }
    )

    identity = current_identity(client)

    assert identity == Identity(
        game_name="Jogador", tag_line="BR1", region="BR", level=1098
    )


def test_a_missing_field_returns_none():
    client = FakeClient(
        {
            CURRENT_SUMMONER: {"gameName": "Jogador", "summonerLevel": 1098},
            RIOT_REGION_LOCALE: {"region": "BR"},
        }
    )

    assert current_identity(client) is None


def test_an_lcu_error_returns_none():
    client = FakeClient({CURRENT_SUMMONER: LcuError("cliente fechado")})

    assert current_identity(client) is None
```

- [ ] **Step 2: Rodar e confirmar que falha por módulo inexistente**

Run: `py -m pytest tests/test_identity.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'lolqueue.core.identity'`

- [ ] **Step 3: Criar `lolqueue/core/identity.py`**

```python
"""Quem está jogando, segundo o próprio cliente do LoL.

Junta dois endpoints que sozinhos não bastam: o nome e o nível vêm de
`current-summoner`, e a região — que o OP.GG exige no formato de sigla
("BR", "KR") — só aparece em `region-locale`, uma rota do Riot Client
servida pela mesma conexão.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..lcu import endpoints
from ..lcu.client import LcuError


@dataclass(frozen=True)
class Identity:
    game_name: str
    tag_line: str
    region: str
    level: int


def current_identity(client) -> Identity | None:
    """Lê quem está conectado agora, ou `None` se algo faltar ou falhar.

    Cliente fechado, sessão ainda não pronta ou resposta incompleta são
    todos o mesmo caso para quem chama: sem identidade, não há como
    perguntar nada ao OP.GG.
    """
    try:
        summoner = client.get(endpoints.CURRENT_SUMMONER)
        locale = client.get(endpoints.RIOT_REGION_LOCALE)
    except LcuError:
        return None
    if not isinstance(summoner, dict) or not isinstance(locale, dict):
        return None

    game_name = summoner.get("gameName")
    tag_line = summoner.get("tagLine")
    level = summoner.get("summonerLevel")
    region = locale.get("region")
    if not game_name or not tag_line or not region or level is None:
        return None
    return Identity(game_name=game_name, tag_line=tag_line, region=region, level=level)
```

- [ ] **Step 4: Rodar de novo**

Run: `py -m pytest tests/test_identity.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add lolqueue/core/identity.py tests/test_identity.py
git commit -m "feat: identidade do invocador conectado (core/identity.py)"
```

---

## Task 4: `core/summoner_history.py`

Perfil e últimas partidas, pelo mesmo servidor MCP do OP.GG.

**Files:**
- Create: `lolqueue/core/summoner_history.py`
- Test: `tests/test_summoner_history.py`

**Interfaces:**
- Consumes: `mcp_format.schema`, `mcp_format.root_data`,
  `mcp_format.unpack`, `mcp_format.entries`, `mcp_format.first`,
  `mcp_format.to_int`, `mcp_format.send_tool` (Task 1).
- Produces (para Tasks 5 e 6 usar):
  `RankEntry(queue_type: str, tier: str | None, division: int | None,
  lp: int | None, wins: int, losses: int)`;
  `Profile(game_name: str, tag_line: str, level: int, ranks: tuple[RankEntry, ...])`;
  `MatchSummary(match_id: str, champion_id: int, champion_name: str,
  result: str, kills: int, deaths: int, assists: int, cs: int,
  duration_seconds: int, queue_type: str, position: str, played_at: datetime)`;
  `SummonerHistorySource().fetch_profile(game_name, tag_line, region, lang="pt_BR") -> Profile | None`;
  `SummonerHistorySource().fetch_matches(game_name, tag_line, region, lang="pt_BR", limit=10) -> tuple[MatchSummary, ...]`;
  `relative_time(played_at: datetime, now: datetime) -> str`.

- [ ] **Step 1: Escrever `tests/test_summoner_history.py` (falha: módulo não existe)**

As respostas abaixo são reais, capturadas ao vivo do servidor MCP do
OP.GG (`lol_get_summoner_profile` e `lol_list_summoner_matches`), com
nome e tag trocados por dados fictícios.

```python
"""Perfil e histórico de partidas: leitura da resposta real do OP.GG.

As respostas embutidas abaixo foram capturadas ao vivo contra
`mcp-api.op.gg`, com o nome e a tag trocados por valores fictícios — o
resto (elos, KDA, ids de campeão, timestamps) é o dado real que o
servidor devolveu.
"""

from datetime import datetime, timezone

from lolqueue.core.summoner_history import (
    MatchSummary,
    Profile,
    RankEntry,
    SummonerHistorySource,
    relative_time,
)

PROFILE = """class LolGetSummonerProfile: data
class Data: summoner
class Summoner: game_name,tagline,level,league_stats
class LeagueStat: game_type,tier_info,win,lose
class TierInfo: tier,division,lp,level,tier_image_url,border_image_url

LolGetSummonerProfile(Data(Summoner("Jogador","BR1",1098,[LeagueStat("SOLORANKED",TierInfo("EMERALD",3,53,null,"https://opgg-static.akamaized.net/images/medals_new/emerald.png","https://opgg-static.akamaized.net/images/border_new/emerald.png"),602,602),LeagueStat("FLEXRANKED",TierInfo("PLATINUM",3,46,null,"https://opgg-static.akamaized.net/images/medals_new/platinum.png","https://opgg-static.akamaized.net/images/border_new/platinum.png"),83,92),LeagueStat("ARENA",TierInfo(null,null,null,null,"https://opgg-static.akamaized.net/images/medals_new/default_unranked.svg",null),null,null)])))"""

BROKEN_PROFILE = """class LolGetSummonerProfile: data
class Data: summoner
class Summoner: game_name,tagline,league_stats
class LeagueStat: game_type,tier_info,win,lose
class TierInfo: tier,division,lp,level,tier_image_url,border_image_url

LolGetSummonerProfile(Data(Summoner("Jogador","BR1",[])))"""

MATCHES = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,stats
class Stats: kill,death,assist,minion_kill,neutral_minion_kill,result

LolListSummonerMatches(Data([GameHistory("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,[Participant(54,"Malphite","TOP",Stats(0,4,0,79,0,"LOSE"))]),GameHistory("wgqT90Iiz731oz69P0WgLhMo6OGiXESPtevq3Dx7SlQ=","2026-08-23T16:25:39+09:00","SOLORANKED",1686,[Participant(22,"Ashe","ADC",Stats(6,6,12,176,12,"WIN"))])]))"""


class FakeSend:
    """Substitui a ida à rede: devolve a resposta certa por ferramenta."""

    def __init__(self, profile_answer="", matches_answer="", fail=False):
        self.profile_answer = profile_answer
        self.matches_answer = matches_answer
        self.fail = fail
        self.calls = []

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.fail:
            raise OSError("sem rede")
        if tool == "lol_get_summoner_profile":
            return self.profile_answer
        return self.matches_answer


# --- perfil -----------------------------------------------------------


def test_a_full_profile_reads_name_level_and_ranks():
    source = SummonerHistorySource(send=FakeSend(profile_answer=PROFILE))

    profile = source.fetch_profile("Jogador", "BR1", "BR")

    assert profile == Profile(
        game_name="Jogador",
        tag_line="BR1",
        level=1098,
        ranks=(
            RankEntry("SOLORANKED", "EMERALD", 3, 53, 602, 602),
            RankEntry("FLEXRANKED", "PLATINUM", 3, 46, 83, 92),
            RankEntry("ARENA", None, None, None, 0, 0),
        ),
    )


def test_an_empty_response_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(profile_answer=""))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_a_missing_field_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(profile_answer=BROKEN_PROFILE))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_a_network_failure_means_no_profile():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    assert source.fetch_profile("Jogador", "BR1", "BR") is None


def test_without_identity_no_request_is_made():
    send = FakeSend(profile_answer=PROFILE)
    source = SummonerHistorySource(send=send)

    assert source.fetch_profile("", "BR1", "BR") is None
    assert send.calls == []


# --- partidas -----------------------------------------------------------


def test_matches_read_a_win_and_a_loss_with_kda_and_cs():
    source = SummonerHistorySource(send=FakeSend(matches_answer=MATCHES))

    matches = source.fetch_matches("Jogador", "BR1", "BR")

    assert matches == (
        MatchSummary(
            match_id="wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
            champion_id=54,
            champion_name="Malphite",
            result="LOSE",
            kills=0,
            deaths=4,
            assists=0,
            cs=79,
            duration_seconds=958,
            queue_type="SOLORANKED",
            position="TOP",
            played_at=datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        ),
        MatchSummary(
            match_id="wgqT90Iiz731oz69P0WgLhMo6OGiXESPtevq3Dx7SlQ=",
            champion_id=22,
            champion_name="Ashe",
            result="WIN",
            kills=6,
            deaths=6,
            assists=12,
            cs=188,
            duration_seconds=1686,
            queue_type="SOLORANKED",
            position="ADC",
            played_at=datetime.fromisoformat("2026-08-23T16:25:39+09:00"),
        ),
    )


def test_an_empty_response_means_no_matches():
    source = SummonerHistorySource(send=FakeSend(matches_answer=""))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()


def test_a_network_failure_means_no_matches():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()


def test_the_limit_is_forwarded_to_the_request():
    send = FakeSend(matches_answer=MATCHES)
    source = SummonerHistorySource(send=send)

    source.fetch_matches("Jogador", "BR1", "BR", limit=10)

    tool, arguments = send.calls[0]
    assert tool == "lol_list_summoner_matches"
    assert arguments["limit"] == 10


# --- tempo relativo -------------------------------------------------------


def test_a_match_from_seconds_ago_reads_as_now():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 0, 30, tzinfo=timezone.utc)

    assert relative_time(played, now) == "agora"


def test_a_match_from_minutes_ago():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 25, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 25 min"


def test_a_match_from_hours_ago():
    played = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 15, 0, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 3 h"


def test_a_match_from_days_ago():
    played = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    assert relative_time(played, now) == "há 3 dias"
```

- [ ] **Step 2: Rodar e confirmar que falha por módulo inexistente**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'lolqueue.core.summoner_history'`

- [ ] **Step 3: Criar `lolqueue/core/summoner_history.py`**

```python
"""Perfil e histórico de partidas, pelo mesmo servidor MCP do OP.GG.

Reaproveita o parser de `core/mcp_format.py` — a resposta chega no
mesmo formato compacto que a build de campeão. Diferente de
`OpggSource`, aqui **não há cache**: histórico envelhece rápido, ao
contrário de build de campeão, que muda pouco durante uma sessão.

Mesma regra de falha do resto do app: rede fora, campo faltando ou
formato mudado vira `None`/`()`, nunca uma exceção para quem chama.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import mcp_format

ENDPOINT = "https://mcp-api.op.gg/mcp"
PROFILE_TOOL = "lol_get_summoner_profile"
MATCHES_TOOL = "lol_list_summoner_matches"

PROFILE_ROOT = "LolGetSummonerProfile"
MATCHES_ROOT = "LolListSummonerMatches"

PROFILE_FIELDS = (
    "data.summoner.{game_name,tagline,level}",
    "data.summoner.league_stats[].{game_type,tier_info,win,lose}",
)
MATCH_FIELDS = (
    "data.game_history[].{id,created_at,game_length_second,game_type}",
    "data.game_history[].participants[].{champion_id,champion_name,position}",
    "data.game_history[].participants[].stats.{kill,death,assist,minion_kill,neutral_minion_kill,result}",
)

DEFAULT_LANG = "pt_BR"
DEFAULT_LIMIT = 10


@dataclass(frozen=True)
class RankEntry:
    """O boletim de uma fila: elo, divisão, PDL e o retrospecto.

    `tier` vem `None` quando a fila não tem elo — o ARENA do OP.GG
    sempre chega assim, e as ranqueadas chegam assim antes da
    colocação.
    """

    queue_type: str
    tier: str | None
    division: int | None
    lp: int | None
    wins: int
    losses: int


@dataclass(frozen=True)
class Profile:
    game_name: str
    tag_line: str
    level: int
    ranks: tuple[RankEntry, ...] = ()


@dataclass(frozen=True)
class MatchSummary:
    """Uma partida, já filtrada pelo servidor para o jogador buscado."""

    match_id: str
    champion_id: int
    #: Em inglês, como o OP.GG manda. A UI troca pelo nome em
    #: português do catálogo já carregado, quando existir.
    champion_name: str
    result: str  # "WIN" | "LOSE"
    kills: int
    deaths: int
    assists: int
    cs: int
    duration_seconds: int
    queue_type: str
    position: str
    played_at: datetime


def relative_time(played_at: datetime, now: datetime) -> str:
    """Há quanto tempo foi jogada: "agora", "há N min", "há N h", "há N dias"."""
    minutes = int((now - played_at).total_seconds() // 60)
    if minutes < 1:
        return "agora"
    if minutes < 60:
        return f"há {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"há {hours} h"
    days = hours // 24
    return f"há {days} dias"


def _rank_entries(value: str, schema: dict[str, list[str]]) -> tuple[RankEntry, ...]:
    found: list[RankEntry] = []
    for entry in mcp_format.entries(value):
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        queue_type = fields.get("game_type", "").strip().strip('"')
        if not queue_type:
            continue
        tier_fields = mcp_format.unpack(fields.get("tier_info"), schema) or {}
        tier_raw = tier_fields.get("tier", "").strip()
        tier = tier_raw.strip('"') if tier_raw and tier_raw != "null" else None
        found.append(
            RankEntry(
                queue_type=queue_type,
                tier=tier,
                division=mcp_format.to_int(tier_fields.get("division", "")),
                lp=mcp_format.to_int(tier_fields.get("lp", "")),
                wins=mcp_format.to_int(fields.get("win", "")) or 0,
                losses=mcp_format.to_int(fields.get("lose", "")) or 0,
            )
        )
    return tuple(found)


def _profile(text: str) -> Profile | None:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, PROFILE_ROOT)
    if data is None:
        return None
    summoner = mcp_format.unpack(data.get("summoner"), schema)
    if summoner is None:
        return None
    game_name = summoner.get("game_name", "").strip().strip('"')
    tag_line = summoner.get("tagline", "").strip().strip('"')
    level = mcp_format.to_int(summoner.get("level", ""))
    if not game_name or not tag_line or level is None:
        return None
    return Profile(
        game_name=game_name,
        tag_line=tag_line,
        level=level,
        ranks=_rank_entries(summoner.get("league_stats", ""), schema),
    )


def _match_summaries(text: str, limit: int) -> tuple[MatchSummary, ...]:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, MATCHES_ROOT)
    if data is None:
        return ()
    found: list[MatchSummary] = []
    for entry in mcp_format.entries(data.get("game_history", "")):
        game = mcp_format.unpack(entry, schema)
        if game is None:
            continue
        match_id = game.get("id", "").strip().strip('"')
        created_at = game.get("created_at", "").strip().strip('"')
        duration = mcp_format.to_int(game.get("game_length_second", ""))
        queue_type = game.get("game_type", "").strip().strip('"')
        participant = mcp_format.first(game.get("participants"))
        fields = mcp_format.unpack(participant, schema) if participant else None
        if fields is None or duration is None or not match_id or not created_at:
            continue
        champion_id = mcp_format.to_int(fields.get("champion_id", ""))
        champion_name = fields.get("champion_name", "").strip().strip('"')
        position = fields.get("position", "").strip().strip('"')
        stats = mcp_format.unpack(fields.get("stats"), schema)
        if champion_id is None or not champion_name or stats is None:
            continue
        kills = mcp_format.to_int(stats.get("kill", ""))
        deaths = mcp_format.to_int(stats.get("death", ""))
        assists = mcp_format.to_int(stats.get("assist", ""))
        minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
        neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
        result = stats.get("result", "").strip().strip('"')
        if kills is None or deaths is None or assists is None or not result:
            continue
        try:
            played_at = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        found.append(
            MatchSummary(
                match_id=match_id,
                champion_id=champion_id,
                champion_name=champion_name,
                result=result,
                kills=kills,
                deaths=deaths,
                assists=assists,
                cs=minions + neutral,
                duration_seconds=duration,
                queue_type=queue_type,
                position=position,
                played_at=played_at,
            )
        )
        if len(found) >= limit:
            break
    return tuple(found)


def _send(tool: str, arguments: dict) -> str:
    return mcp_format.send_tool(ENDPOINT, tool, arguments)


class SummonerHistorySource:
    """Busca perfil e partidas recentes. Sem cache: o dado envelhece rápido."""

    def __init__(self, send: Callable[[str, dict], str] | None = None) -> None:
        self._send = send or _send

    def fetch_profile(
        self, game_name: str, tag_line: str, region: str, lang: str = DEFAULT_LANG
    ) -> Profile | None:
        if not game_name or not tag_line or not region:
            return None
        try:
            text = self._send(
                PROFILE_TOOL,
                {
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "region": region,
                    "lang": lang,
                    "desired_output_fields": list(PROFILE_FIELDS),
                },
            )
        except Exception:
            return None
        return _profile(text or "")

    def fetch_matches(
        self,
        game_name: str,
        tag_line: str,
        region: str,
        lang: str = DEFAULT_LANG,
        limit: int = DEFAULT_LIMIT,
    ) -> tuple[MatchSummary, ...]:
        if not game_name or not tag_line or not region:
            return ()
        try:
            text = self._send(
                MATCHES_TOOL,
                {
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "region": region,
                    "lang": lang,
                    "limit": limit,
                    "desired_output_fields": list(MATCH_FIELDS),
                },
            )
        except Exception:
            return ()
        return _match_summaries(text or "", limit)
```

- [ ] **Step 4: Rodar de novo**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: PASS (todos os testes)

- [ ] **Step 5: Commit**

```bash
git add lolqueue/core/summoner_history.py tests/test_summoner_history.py
git commit -m "feat: perfil e historico de partidas via OP.GG (core/summoner_history.py)"
```

---

## Task 5: `ui/pages/history.py`

A página, testável isoladamente com dados sintéticos — ainda não
plugada na janela.

**Files:**
- Create: `lolqueue/ui/pages/history.py`
- Test: `tests/test_history_page.py`

**Interfaces:**
- Consumes: `Profile`, `RankEntry`, `MatchSummary`, `relative_time`
  (Task 4).
- Produces (para Task 7 usar): `HistoryPage` com
  `refresh_requested: Signal()`,
  `set_icon_resolver(resolve: Callable[[int], str | None]) -> None`,
  `set_name_resolver(resolve: Callable[[int], str | None]) -> None`,
  `set_history(profile: Profile | None, matches: tuple[MatchSummary, ...]) -> None`.

- [ ] **Step 1: Escrever `tests/test_history_page.py` (falha: módulo não existe)**

```python
"""A página de histórico: o que mostra, e quando volta ao vazio."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.core.summoner_history import (  # noqa: E402
    MatchSummary,
    Profile,
    RankEntry,
)
from lolqueue.ui.pages.history import HistoryPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app):
    return HistoryPage()


def profile(**changes):
    base = dict(
        game_name="Jogador",
        tag_line="BR1",
        level=1098,
        ranks=(
            RankEntry("SOLORANKED", "EMERALD", 3, 53, 602, 602),
            RankEntry("ARENA", None, None, None, 0, 0),
        ),
    )
    base.update(changes)
    return Profile(**base)


def match(**changes):
    base = dict(
        match_id="abc",
        champion_id=22,
        champion_name="Ashe",
        result="WIN",
        kills=6,
        deaths=6,
        assists=12,
        cs=188,
        duration_seconds=1686,
        queue_type="SOLORANKED",
        position="ADC",
        played_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(changes)
    return MatchSummary(**base)


def test_it_starts_with_nothing_to_read(page):
    assert page._content.isHidden()
    assert not page._empty.isHidden()


def test_a_profile_that_never_came_keeps_the_empty_notice(page):
    page.set_history(None, ())

    assert page._content.isHidden()
    assert not page._empty.isHidden()


def test_a_full_profile_shows_name_and_level(page):
    page.set_history(profile(), (match(),))

    assert page._content.isVisible() or not page._content.isHidden()
    assert "Jogador#BR1" in page._name.text()
    assert "1098" in page._level.text()


def test_the_match_row_shows_champion_and_kda(page):
    page.set_history(profile(), (match(),))

    row_layout = page._matches_box.itemAt(0).widget().layout()
    texts = []

    def collect(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                texts.append(widget.text() if hasattr(widget, "text") else "")
            elif item.layout() is not None:
                collect(item.layout())

    collect(row_layout)
    joined = " ".join(texts)
    assert "Ashe" in joined
    assert "6/6/12" in joined


def test_the_refresh_button_asks_for_a_new_query(page, qtbot=None):
    seen = []
    page.refresh_requested.connect(lambda: seen.append(True))

    page._refresh_button.click()

    assert seen == [True]
```

- [ ] **Step 2: Rodar e confirmar que falha por módulo inexistente**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'lolqueue.ui.pages.history'`

- [ ] **Step 3: Criar `lolqueue/ui/pages/history.py`**

```python
"""Perfil e últimas partidas do invocador conectado, pelo OP.GG.

Cabeçalho com nick#tag, nível e elo por fila — só texto: o único ícone
remoto seria o retrato de perfil do OP.GG, e baixar imagem de URL
arbitrária seria um mecanismo novo para um ganho cosmético (a única
imagem que o app já sabe buscar e cachear é o retrato de campeão, por
id, via LCU). Abaixo, uma linha por partida, reaproveitando esse mesmo
cache de retrato.

Sem cliente aberto, sem identidade resolvida ou falha do OP.GG: mesmo
aviso de vazio que `AnalysisPage` já usa — um cabeçalho vazio com uma
lista de partidas por baixo pareceria defeito, e não é.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.summoner_history import relative_time

MATCH_PORTRAIT = QSize(40, 40)

#: Como o OP.GG chama a fila, e como se diz aqui.
QUEUE_LABELS = {
    "SOLORANKED": "Ranqueada Solo/Duo",
    "FLEXRANKED": "Ranqueada Flexível",
    "ARAM": "ARAM",
    "NORMAL": "Normal",
    "ARENA": "Arena",
}

#: Só estas duas filas têm elo que faz sentido estampar no cabeçalho.
RANK_QUEUE_LABELS = {
    "SOLORANKED": "Solo/Duo",
    "FLEXRANKED": "Flexível",
}


def _duration_text(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


class HistoryPage(QWidget):
    """Perfil e últimas partidas, puxados do OP.GG sob pedido."""

    #: A tela pede uma consulta nova. Quem busca é a janela — esta
    #: página não fala com a rede.
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve_icon = None
        self._resolve_name = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(1)
        title = QLabel("HISTÓRICO DE PARTIDAS")
        title.setObjectName("pageTitle")
        words.addWidget(title)
        subtitle = QLabel("As últimas partidas do invocador conectado, pelo OP.GG.")
        subtitle.setObjectName("pageSubtitle")
        words.addWidget(subtitle)
        heading.addLayout(words)
        heading.addStretch(1)
        self._refresh_button = QPushButton("Atualizar")
        self._refresh_button.setObjectName("primaryButton")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        # O aviso de vazio e o conteúdo se revezam, igual à análise: um
        # dos dois está sempre escondido, e nunca os dois ao mesmo tempo.
        self._empty = QLabel(
            "Nada por enquanto. Abra o cliente do LoL para ver perfil e "
            "partidas recentes."
        )
        self._empty.setObjectName("listNotice")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        layout.addWidget(self._content)
        self._content.hide()

        content.addWidget(self._build_hero())
        self._matches_box = QVBoxLayout()
        self._matches_box.setSpacing(8)
        content.addLayout(self._matches_box)
        content.addStretch(1)

    def _build_hero(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(24, 16, 24, 16)
        row.setSpacing(18)

        naming = QVBoxLayout()
        naming.setSpacing(2)
        self._name = QLabel()
        self._name.setObjectName("heroHeadline")
        naming.addWidget(self._name)
        self._level = QLabel()
        self._level.setObjectName("heroDetail")
        naming.addWidget(self._level)
        row.addLayout(naming)
        row.addStretch(1)

        self._ranks = QHBoxLayout()
        self._ranks.setSpacing(22)
        row.addLayout(self._ranks)
        return card

    def set_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de campeão em caminho de retrato.

        Chega tarde, junto com os retratos: enquanto não chega, as
        partidas aparecem só com o nome, que já basta para ler.
        """
        self._resolve_icon = resolve

    def set_name_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de campeão em nome português.

        O OP.GG manda o nome em inglês; enquanto o catálogo de
        campeões não carregou, a linha usa o nome que veio junto.
        """
        self._resolve_name = resolve

    def set_history(self, profile, matches) -> None:
        """Mostra perfil e partidas, ou volta ao aviso de vazio.

        `profile` vindo `None` é "sem identidade resolvida ou o OP.GG
        não respondeu" — a página toda some, como na análise.
        """
        if profile is None:
            self._content.hide()
            self._empty.show()
            return

        self._name.setText(f"{profile.game_name}#{profile.tag_line}")
        self._level.setText(f"Nível {profile.level}")
        self._fill_ranks(profile.ranks)
        self._fill_matches(matches)

        self._empty.hide()
        self._content.show()

    def _fill_ranks(self, ranks) -> None:
        while self._ranks.count():
            item = self._ranks.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for rank in ranks:
            label = RANK_QUEUE_LABELS.get(rank.queue_type)
            if label is None or rank.tier is None:
                continue
            games = rank.wins + rank.losses
            rate = f"{rank.wins / games:.0%}" if games else "—"
            value = f"{rank.tier.title()} {rank.division} · {rank.lp} PDL"
            self._ranks.addWidget(self._measure(label.upper(), f"{value}  ({rate})"))

    @staticmethod
    def _measure(label: str, value: str) -> QWidget:
        block = QWidget()
        box = QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        top = QLabel(label)
        top.setObjectName("cardLabel")
        box.addWidget(top, 0, Qt.AlignmentFlag.AlignHCenter)
        bottom = QLabel(value)
        bottom.setObjectName("cardValue")
        box.addWidget(bottom, 0, Qt.AlignmentFlag.AlignHCenter)
        return block

    def _fill_matches(self, matches) -> None:
        while self._matches_box.count():
            item = self._matches_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        now = datetime.now(timezone.utc)
        for match in matches:
            self._matches_box.addWidget(self._match_row(match, now))

    def _match_row(self, match, now) -> QFrame:
        row = QFrame()
        row.setObjectName("optionCard")
        box = QHBoxLayout(row)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(14)

        portrait = QLabel()
        portrait.setFixedSize(MATCH_PORTRAIT)
        portrait.setScaledContents(True)
        path = self._resolve_icon(match.champion_id) if self._resolve_icon else None
        icon = QIcon(path) if path else QIcon()
        portrait.setPixmap(icon.pixmap(MATCH_PORTRAIT))
        box.addWidget(portrait)

        naming = QVBoxLayout()
        naming.setSpacing(1)
        name = self._resolve_name(match.champion_id) if self._resolve_name else None
        champion = QLabel(name or match.champion_name)
        champion.setObjectName("predictionName")
        naming.addWidget(champion)
        result = "Vitória" if match.result == "WIN" else "Derrota"
        mode = QUEUE_LABELS.get(match.queue_type, match.queue_type)
        detail = QLabel(f"{result} · {mode}")
        detail.setObjectName("heroDetail")
        naming.addWidget(detail)
        box.addLayout(naming)
        box.addStretch(1)

        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setObjectName("cardValue")
        box.addWidget(kda)

        cs = QLabel(f"{match.cs} CS")
        cs.setObjectName("heroDetail")
        box.addWidget(cs)

        duration = QLabel(_duration_text(match.duration_seconds))
        duration.setObjectName("heroDetail")
        box.addWidget(duration)

        when = QLabel(relative_time(match.played_at, now))
        when.setObjectName("hint")
        box.addWidget(when)
        return row
```

- [ ] **Step 4: Rodar de novo**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: PASS (todos os testes)

- [ ] **Step 5: Commit**

```bash
git add lolqueue/ui/pages/history.py tests/test_history_page.py
git commit -m "feat: pagina de historico de partidas (ui/pages/history.py)"
```

---

## Task 6: `ui/history_loader.py`

`QThread` que encadeia identidade (LCU) → perfil e partidas (OP.GG),
no molde de `MatchupLoader`. Sem teste dedicado: convenção já existente
no projeto — `IconLoader` e `MatchupLoader`, os outros dois loaders,
também não têm teste próprio; a lógica de negócio que importa
(`current_identity`, `SummonerHistorySource`) já está coberta nas
Tasks 3 e 4, e o que resta aqui é só fiação de thread.

**Files:**
- Create: `lolqueue/ui/history_loader.py`

**Interfaces:**
- Consumes: `current_identity(client)` (Task 3), `SummonerHistorySource`
  (Task 4), `discover()` e `LcuClient` de `lolqueue.lcu`.
- Produces (para Task 7 usar): `HistoryLoader(source, parent=None)`
  com `ready: Signal(object, object)` emitindo `(Profile | None,
  tuple[MatchSummary, ...])`, método `start()` herdado de `QThread`.

- [ ] **Step 1: Criar `lolqueue/ui/history_loader.py`**

```python
"""Busca perfil e histórico de partidas fora da thread da tela.

Ao contrário do `MatchupLoader`, que já recebe os dois lados prontos,
este loader primeiro precisa descobrir quem está jogando: abre a
própria conexão com o cliente do LoL, lê a identidade e só então
consulta o OP.GG. Uma consulta por vez — entrar e sair da página várias
vezes não deve empilhar threads pedindo a mesma coisa; quem garante
isso é a janela, que só cria um loader novo se o anterior já terminou.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.identity import current_identity
from ..core.summoner_history import SummonerHistorySource
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class HistoryLoader(QThread):
    #: `(Profile | None, tuple[MatchSummary, ...])`. `object` porque
    #: são classes nossas e o perfil pode vir `None`.
    ready = Signal(object, object)

    def __init__(self, source: SummonerHistorySource, parent=None) -> None:
        super().__init__(parent)
        self._source = source

    def run(self) -> None:
        profile = None
        matches: tuple = ()
        try:
            credentials = discover()
            if credentials is not None:
                client = LcuClient(credentials)
                identity = current_identity(client)
                if identity is not None:
                    profile = self._source.fetch_profile(
                        identity.game_name, identity.tag_line, identity.region
                    )
                    matches = self._source.fetch_matches(
                        identity.game_name, identity.tag_line, identity.region
                    )
        except Exception:
            # Cliente fechado no meio da consulta, DNS falhando, o que
            # for: quem chama só precisa saber que não há dado agora.
            profile, matches = None, ()
        self.ready.emit(profile, matches)
```

- [ ] **Step 2: Conferir que o módulo importa sem erro**

Run: `py -c "from lolqueue.ui.history_loader import HistoryLoader"`
Expected: nenhuma saída (import limpo)

- [ ] **Step 3: Rodar a suite inteira, para garantir que nada quebrou**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add lolqueue/ui/history_loader.py
git commit -m "feat: thread de busca do historico (ui/history_loader.py)"
```

---

## Task 7: Fiação — sidebar, ícone e janela

Última etapa: liga a página nova à navegação. Sidebar, asset e
`window.py` mudam juntos porque um sem o outro deixa `test_window.py`
vermelho — não faz sentido dividir em tasks que se quebram mutuamente.

**Files:**
- Create: `lolqueue/assets/nav-history.svg`
- Modify: `lolqueue/ui/widgets/sidebar.py:21-27`
- Modify: `lolqueue/ui/window.py` (import, `__init__`, `_build`,
  `_navigate`, novo `_refresh_history`/`_retire_history_loader`/
  `_on_history_ready`/`_champion_name`, `closeEvent`)
- Modify: `tests/test_window.py:172-178`

**Interfaces:**
- Consumes: `HistoryPage` (Task 5), `HistoryLoader` (Task 6),
  `SummonerHistorySource` (Task 4).

- [ ] **Step 1: Criar o ícone `lolqueue/assets/nav-history.svg`**

Mesmo estilo dos outros ícones da barra (traço, sem preenchimento, as
duas cores da marca): um relógio com uma seta ao redor, para sugerir
"olhar para trás no tempo".

```svg
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 21a9 9 0 1 0-9-9" stroke="#C8AA6E" stroke-width="1.7" stroke-linecap="round"/><path d="M3 7v5h5" stroke="#C8AA6E" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 8v4l3 2" stroke="#52D8D0" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
```

- [ ] **Step 2: Atualizar `tests/test_window.py` primeiro, para ver o vermelho certo**

Em `tests/test_window.py:21`, adicionar o import:

```python
from lolqueue.ui.pages.history import HistoryPage  # noqa: E402
```

(mantendo a lista alfabética de imports de páginas: `AnalysisPage`,
`ChampionsPage`, `DashboardPage`, `HistoryPage`, `QueuePage`,
`SettingsPage`.)

Em `tests/test_window.py:172-178`, o dicionário `esperado` ganha a
entrada nova, na posição em que `SECTIONS` vai colocá-la:

```python
    esperado = {
        "Painel": DashboardPage,
        "Análise": AnalysisPage,
        "Histórico": HistoryPage,
        "Campeões": ChampionsPage,
        "Fila": QueuePage,
        "Ajustes": SettingsPage,
    }
```

- [ ] **Step 3: Rodar e confirmar que falha (SECTIONS ainda não tem "Histórico")**

Run: `py -m pytest tests/test_window.py -v`
Expected: FAIL em `test_every_sidebar_button_opens_the_page_that_matches_it`
com `AssertionError` (o `assert {name for name, _ in SECTIONS} == set(esperado)` não bate)

- [ ] **Step 4: Adicionar a seção em `lolqueue/ui/widgets/sidebar.py`**

Em `lolqueue/ui/widgets/sidebar.py:21-27`, trocar:

```python
SECTIONS = (
    ("Painel", "nav-dashboard.svg"),
    ("Análise", "nav-analysis.svg"),
    ("Campeões", "nav-champions.svg"),
    ("Fila", "nav-queue.svg"),
    ("Ajustes", "nav-settings.svg"),
)
```

por:

```python
SECTIONS = (
    ("Painel", "nav-dashboard.svg"),
    ("Análise", "nav-analysis.svg"),
    ("Histórico", "nav-history.svg"),
    ("Campeões", "nav-champions.svg"),
    ("Fila", "nav-queue.svg"),
    ("Ajustes", "nav-settings.svg"),
)
```

- [ ] **Step 5: Rodar de novo — agora falha na contagem de páginas, não mais no nome**

Run: `py -m pytest tests/test_window.py -v`
Expected: FAIL em `test_the_stack_has_exactly_one_page_per_section`
(`window._pages.count() == len(SECTIONS)` não bate: a pilha ainda tem
5 páginas para 6 seções) — e possivelmente em
`test_every_sidebar_button_opens_the_page_that_matches_it`, já que o
índice 2 agora abre `ChampionsPage` em vez de `HistoryPage`.

- [ ] **Step 6: Editar `lolqueue/ui/window.py` — imports**

Em `lolqueue/ui/window.py:22-23`, depois de `from ..core.matchup import
MatchupSource`, adicionar (mantendo ordem alfabética das linhas de
`..core`):

```python
from ..core.matchup import MatchupSource
from ..core.opgg import OpggSource
from ..core.summoner_history import SummonerHistorySource
```

Em `lolqueue/ui/window.py:29`, depois de `from .matchup_loader import
MatchupLoader`, adicionar:

```python
from .history_loader import HistoryLoader
from .matchup_loader import MatchupLoader
```

Em `lolqueue/ui/window.py:30-34`, adicionar o import da página (ordem
alfabética das páginas):

```python
from .pages.analysis import AnalysisPage
from .pages.champions import ChampionsPage
from .pages.dashboard import DashboardPage
from .pages.history import HistoryPage
from .pages.queue import QueuePage
from .pages.settings import SettingsPage
```

- [ ] **Step 7: Editar `lolqueue/ui/window.py` — `__init__`**

Em `lolqueue/ui/window.py:80-83`, depois do bloco de `self._matchups`
e `self._matchup_loader`, adicionar (mesmo espírito do comentário já
ali: fonte sobrevive fora do motor, loader guardado à parte):

```python
        self._matchups = MatchupSource()
        self._matchup_loader: MatchupLoader | None = None
        # O perfil e as partidas consultados, pelo mesmo motivo do
        # `_opgg` e do `_matchups`: sobrevivem a uma reconexão.
        self._history_source = SummonerHistorySource()
        self._history_loader: HistoryLoader | None = None
```

- [ ] **Step 8: Editar `lolqueue/ui/window.py` — `_build`**

Em `lolqueue/ui/window.py:146-164`, trocar:

```python
        self._analysis = AnalysisPage()
        self._analysis.set_icon_resolver(self._champion_icon)
        self._analysis.matchup_requested.connect(self._on_matchup_requested)
        self._champions = ChampionsPage(self._binder)
        self._queue = QueuePage(self._binder)

        # A ordem tem de bater com `SECTIONS` da barra lateral: é o
        # índice do botão que escolhe a página.
        self._pages = QStackedWidget()
        for page in (
            self._dashboard,
            self._analysis,
            self._champions,
            self._queue,
            SettingsPage(self._binder),
        ):
            self._pages.addWidget(self._scroll_page(page))
```

por:

```python
        self._analysis = AnalysisPage()
        self._analysis.set_icon_resolver(self._champion_icon)
        self._analysis.matchup_requested.connect(self._on_matchup_requested)
        self._history = HistoryPage()
        self._history.set_icon_resolver(self._champion_icon)
        self._history.set_name_resolver(self._champion_name)
        self._history.refresh_requested.connect(self._refresh_history)
        self._champions = ChampionsPage(self._binder)
        self._queue = QueuePage(self._binder)

        # A ordem tem de bater com `SECTIONS` da barra lateral: é o
        # índice do botão que escolhe a página.
        self._pages = QStackedWidget()
        for page in (
            self._dashboard,
            self._analysis,
            self._history,
            self._champions,
            self._queue,
            SettingsPage(self._binder),
        ):
            self._pages.addWidget(self._scroll_page(page))
```

- [ ] **Step 9: Editar `lolqueue/ui/window.py` — `_navigate` dispara a consulta ao abrir a página**

Em `lolqueue/ui/window.py:180-181`, trocar:

```python
    def _navigate(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
```

por:

```python
    #: Índice de "Histórico" em `SECTIONS` — mesma amarração por
    #: posição que o resto de `_build` já usa.
    _HISTORY_INDEX = 2

    def _navigate(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        if index == self._HISTORY_INDEX:
            self._refresh_history()
```

- [ ] **Step 10: Editar `lolqueue/ui/window.py` — novos métodos de histórico**

Logo depois de `_retire_matchup_loader` (após `lolqueue/ui/window.py:367`,
antes de `_on_analysis_changed`), adicionar:

```python
    def _refresh_history(self) -> None:
        """Busca perfil e partidas numa thread só dela.

        Uma consulta por vez: se já há uma rodando, o pedido novo (um
        segundo clique em "Atualizar", ou abrir a página de novo bem
        rápido) não faz nada — a que já está a caminho responde para
        os dois casos.
        """
        if self._history_loader is not None:
            return
        loader = HistoryLoader(self._history_source, self)
        loader.ready.connect(self._on_history_ready)
        loader.finished.connect(lambda: self._retire_history_loader(loader))
        self._history_loader = loader
        loader.start()

    def _retire_history_loader(self, loader) -> None:
        if self._history_loader is loader:
            self._history_loader = None
        loader.deleteLater()

    def _on_history_ready(self, profile, matches) -> None:
        self._history.set_history(profile, matches)

    def _champion_name(self, champion_id: int) -> str | None:
        """O nome em português do campeão, se o catálogo já carregou.

        Serve às partidas do histórico, que vêm do OP.GG com o nome em
        inglês. Sem catálogo ainda (app recém-aberto), a linha usa o
        nome que já veio na resposta.
        """
        return self._latest_catalog.name(champion_id) if self._latest_catalog else None
```

- [ ] **Step 11: Editar `lolqueue/ui/window.py` — `closeEvent`**

Em `lolqueue/ui/window.py:474-479`, depois do bloco de
`self._matchup_loader`, adicionar:

```python
        if self._matchup_loader is not None:
            # Não tem como pedir para parar: está bloqueado numa
            # resposta HTTP. Esperar o timeout da consulta é curto o
            # bastante, e sair sem esperar deixaria o Qt destruir uma
            # thread ainda rodando.
            self._matchup_loader.wait(3000)
        if self._history_loader is not None:
            self._history_loader.wait(3000)
        event.accept()
```

- [ ] **Step 12: Rodar a suite de janela**

Run: `py -m pytest tests/test_window.py -v`
Expected: PASS (todos os testes, incluindo os dois de alinhamento de
`SECTIONS`)

- [ ] **Step 13: Rodar a suite inteira do projeto**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 14: Verificação ao vivo — abrir o app de verdade**

Com o cliente do LoL aberto:

Run: `py -m lolqueue`

Clicar em "Histórico" na barra lateral e conferir visualmente: nick,
nível, elo(s), e as últimas partidas com campeão, resultado, KDA, CS,
duração, modo e tempo relativo aparecem. Clicar em "Atualizar" e
conferir que a consulta roda de novo sem travar a janela.

- [ ] **Step 15: Commit**

```bash
git add lolqueue/assets/nav-history.svg lolqueue/ui/widgets/sidebar.py \
        lolqueue/ui/window.py tests/test_window.py
git commit -m "feat: liga a pagina de historico na navegacao"
```

---

## Self-Review

**1. Cobertura da spec:**
- Nick#tag, nível, elo por fila → `Profile`/`RankEntry` (Task 4) +
  cabeçalho de `HistoryPage` (Task 5). ✅
- Últimas 10 partidas com resultado, campeão, KDA, CS, duração, modo,
  tempo relativo → `MatchSummary` + `_match_row` (Task 5),
  `DEFAULT_LIMIT = 10` (Task 4). ✅
- Nova entrada na barra lateral entre Análise e Campeões → Task 7. ✅
- `core/mcp_format.py` extraído, `opgg.py` sem mudança de
  comportamento → Task 1, verificado contra `test_opgg.py` antes e
  depois. ✅
- `core/identity.py` lendo os dois endpoints da LCU → Task 3. ✅
- `RIOT_REGION_LOCALE` → Task 2. ✅
- `ui/history_loader.py` no molde de `MatchupLoader` → Task 6. ✅
- Sem cache em `SummonerHistorySource` → confirmado no código da
  Task 4 (nenhum dict de cache, ao contrário de `OpggSource`). ✅
- Sem download de ícone remoto de perfil → `HistoryPage` (Task 5) só
  usa texto no cabeçalho e o resolvedor de ícone por id (LCU). ✅
- `relative_time` testável sem Qt → função pura em
  `core/summoner_history.py`, testada na Task 4. ✅
- `test_window.py` com `"Histórico": HistoryPage` → Task 7. ✅
- Fora de escopo (detalhe de partida, outro invocador, tempo real,
  gráfico de elo) → nenhuma task implementa nada disso. ✅

**2. Placeholders:** nenhum "TBD"/"implementar depois" — toda task tem
código completo e executável, inclusive as fixtures de teste (dados
reais capturados ao vivo, com identidade trocada por fictícia).

**3. Consistência de tipos entre tasks:**
- `Identity(game_name, tag_line, region, level)` (Task 3) → consumido
  por `HistoryLoader.run()` (Task 6) exatamente com esses 3 atributos
  posicionais (`identity.game_name`, `.tag_line`, `.region`). ✅
- `SummonerHistorySource.fetch_profile(game_name, tag_line, region)` e
  `.fetch_matches(game_name, tag_line, region)` (Task 4) → chamados
  com esses mesmos nomes posicionais em `HistoryLoader.run()`
  (Task 6). ✅
- `HistoryLoader.ready` emite `(Profile | None, tuple[MatchSummary,
  ...])` (Task 6) → `_on_history_ready(self, profile, matches)`
  (Task 7) passa direto para `HistoryPage.set_history(profile,
  matches)` (Task 5), mesma ordem e mesmos tipos. ✅
- `HistoryPage.set_icon_resolver`/`set_name_resolver` (Task 5) →
  ligados em `_build` (Task 7) a `self._champion_icon` (já existente)
  e ao novo `self._champion_name` (Task 7). ✅
- `mcp_format.root_data(text, schema, root)` (Task 1) → chamado em
  `opgg.py` como `mcp_format.root_data(text, schema, ROOT)` (Task 1) e
  em `summoner_history.py` como `mcp_format.root_data(text, schema,
  PROFILE_ROOT)` / `MATCHES_ROOT` (Task 4) — mesma assinatura de 3
  posicionais nos dois usos. ✅
