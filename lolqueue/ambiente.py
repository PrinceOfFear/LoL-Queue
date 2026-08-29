"""O que precisa estar instalado para o app abrir — e o que falta.

Existe por causa do atalho. Quem abre o app é o `pythonw.exe`, que não
tem console: numa máquina onde falta uma dependência o import morre, o
traceback vai para um lugar que ninguém lê e o duplo clique não produz
absolutamente nada — nem janela, nem erro, nem ícone na barra. Foi
exatamente assim que o app "não funcionou" no outro PC. Perguntar antes
é o que transforma esse nada em uma frase.

A lista de requisitos sai do `pyproject.toml`, não daqui. Duas listas
viram uma lista desatualizada, e isso já custou caro uma vez: a máquina
que instalou só o que estava declarado ficou muda a partida inteira
porque o `edge-tts` não estava na declaração.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

#: A raiz do repositório, contada a partir deste arquivo.
RAIZ = Path(__file__).resolve().parent.parent

#: Onde as dependências estão declaradas de verdade.
PYPROJECT = RAIZ / "pyproject.toml"

#: Só o nome do pacote: `PySide6>=6.10` vira `PySide6`. Extras e
#: marcadores também caem aqui porque nenhum deles faz parte do nome.
_NOME = re.compile(r"^[A-Za-z0-9._-]+")


def requisitos() -> tuple[str, ...]:
    """Os nomes que o `pip install` receberia, na ordem declarada.

    Devolve vazio quando o `pyproject.toml` não está do lado — é o caso
    do executável compilado, onde o arquivo não viaja junto e as
    dependências já foram embutidas. Nada declarado, nada a cobrar.
    """
    try:
        dados = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    declaradas = dados.get("project", {}).get("dependencies", [])
    nomes = []
    for linha in declaradas:
        achado = _NOME.match(linha.strip())
        if achado is not None:
            nomes.append(achado.group(0))
    return tuple(nomes)


def modulo(distribuicao: str) -> str:
    """O nome que o `import` usa, a partir do nome que o `pip` usa.

    São coisas diferentes — `edge-tts` se importa como `edge_tts` — e o
    mapa oficial (`packages_distributions`) só conhece o que já está
    instalado, ou seja, justamente o que não interessa aqui. A troca do
    hífen por sublinhado é a regra que acerta as seis dependências
    declaradas hoje; uma que fuja disso precisa de uma linha aqui.
    """
    return distribuicao.replace("-", "_")


def _instalado(nome: str) -> bool:
    try:
        return importlib.util.find_spec(modulo(nome)) is not None
    except (ImportError, ValueError):
        return False


def faltando() -> list[str]:
    """As dependências declaradas que não estão instaladas.

    Pergunta ao localizador de módulos em vez de importar: importar o
    PySide6 inteiro para descobrir que ele existe custa segundos, e num
    caminho de erro isso é tempo em cima de quem já está travado.
    """
    return [nome for nome in requisitos() if not _instalado(nome)]


def queixa(faltantes: list[str]) -> str:
    """O texto que a máquina nova precisa ler, com o conserto junto."""
    lista = ", ".join(faltantes) if faltantes else "uma dependência"
    return (
        "O LoL Queue não abriu porque falta instalar: "
        f"{lista}.\n\n"
        "Rode isto uma vez, dentro da pasta do app:\n\n"
        r"    powershell -ExecutionPolicy Bypass -File tools\instalar.ps1"
    )
