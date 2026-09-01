"""O que precisa estar instalado para o app abrir — e o que falta.

Existe por causa do atalho. Quem abre o app é o `pythonw.exe`, que não
tem console: numa máquina onde falta uma dependência o import morre, o
traceback vai para um lugar que ninguém lê e o duplo clique não produz
absolutamente nada — nem janela, nem erro, nem ícone na barra. Foi
exatamente assim que o app "não funcionou" no outro PC. Perguntar antes
é o que transforma esse nada em uma frase.

A lista de requisitos sai do `pyproject.toml`, não daqui. Duas listas
viram uma lista desatualizada, então há uma única fonte de verdade para
o instalador Python e para esta conferência.
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


def pacotes_instalacao() -> tuple[str, ...]:
    """As dependências exatamente como foram declaradas para o ``pip``.

    O instalador da versão Python precisa preservar limites como
    ``PySide6>=6.10``. Entregar somente ``PySide6`` deixa uma instalação
    antiga aparentemente válida, embora ela possa não ter as APIs que o
    aplicativo usa.

    Devolve vazio quando o ``pyproject.toml`` não está ao lado — caso do
    executável compilado, em que as dependências já foram embutidas.
    """
    try:
        dados = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    declaradas = dados.get("project", {}).get("dependencies", [])
    if not isinstance(declaradas, list):
        return ()
    pacotes = []
    for linha in declaradas:
        if not isinstance(linha, str):
            continue
        pacote = linha.strip()
        achado = _NOME.match(pacote)
        if achado is not None:
            pacotes.append(pacote)
    return tuple(pacotes)


def requisitos() -> tuple[str, ...]:
    """Somente os nomes dos pacotes, para conferir se os imports existem."""
    nomes = []
    for pacote in pacotes_instalacao():
        achado = _NOME.match(pacote)
        if achado is not None:
            nomes.append(achado.group(0))
    return tuple(nomes)


def modulo(distribuicao: str) -> str:
    """O nome que o `import` usa, a partir do nome que o `pip` usa.

    São coisas diferentes — um pacote com hífen usa sublinhado no import —
    e o mapa oficial (`packages_distributions`) só conhece o que já está
    instalado, ou seja, justamente o que não interessa aqui. A troca do
    hífen por sublinhado cobre as dependências declaradas; uma que fuja
    disso precisa de uma linha aqui.
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
