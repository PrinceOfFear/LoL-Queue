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


def to_bool(value: str) -> bool | None:
    """Lê o `true`/`false` cru que o servidor manda para booleano.

    Sem aspas e sem `True`/`False` do Python — o valor chega
    exatamente como veio no campo `is_win`/`is_target` da resposta.
    """
    text = value.strip()
    if text == "true":
        return True
    if text == "false":
        return False
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
