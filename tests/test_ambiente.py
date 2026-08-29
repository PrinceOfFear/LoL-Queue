"""A conferência de dependências que o atalho não fazia.

Ela existe para um caso que não dá para reproduzir aqui — a máquina
onde falta o PySide6 — então o que os testes cobram é o que sobra: os
nomes vêm do `pyproject.toml`, a tradução para nome de import está
certa, e a ausência do arquivo não vira exceção.
"""

import ast
import sys
from pathlib import Path

from lolqueue import ambiente


def test_the_requirements_come_from_the_declaration():
    assert "PySide6" in ambiente.requisitos()
    assert "edge-tts" in ambiente.requisitos()


def test_the_version_specifier_is_not_part_of_the_name():
    for nome in ambiente.requisitos():
        assert ">" not in nome
        assert "=" not in nome


def test_the_voice_is_declared_because_a_silent_machine_costs_a_game():
    """Ficou de fora uma vez e o app abriu normalmente, e mudo."""
    assert "edge-tts" in ambiente.requisitos()


def test_the_pip_name_is_translated_to_the_import_name():
    assert ambiente.modulo("edge-tts") == "edge_tts"
    assert ambiente.modulo("PySide6") == "PySide6"


def test_a_missing_pyproject_charges_nothing(monkeypatch):
    """No executável compilado o arquivo não viaja junto."""
    monkeypatch.setattr(ambiente, "PYPROJECT", Path("nao-existe.toml"))
    assert ambiente.requisitos() == ()
    assert ambiente.faltando() == []


def test_a_broken_pyproject_charges_nothing(tmp_path, monkeypatch):
    quebrado = tmp_path / "pyproject.toml"
    quebrado.write_text("[project\nisto nao e toml", encoding="utf-8")
    monkeypatch.setattr(ambiente, "PYPROJECT", quebrado)
    assert ambiente.requisitos() == ()


def test_what_is_installed_here_is_not_reported_as_missing():
    assert ambiente.faltando() == []


def test_a_dependency_nobody_ever_published_is_reported_missing(tmp_path, monkeypatch):
    falso = tmp_path / "pyproject.toml"
    falso.write_text(
        '[project]\ndependencies = ["nao-existe-mesmo>=1.0"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(ambiente, "PYPROJECT", falso)
    assert ambiente.faltando() == ["nao-existe-mesmo"]


def test_the_complaint_names_what_is_missing_and_how_to_fix_it():
    texto = ambiente.queixa(["edge-tts"])
    assert "edge-tts" in texto
    assert "instalar.ps1" in texto


def test_the_complaint_still_helps_when_the_list_came_out_empty():
    """Import quebrado sem dependência faltando é possível; mudo, não."""
    assert "instalar.ps1" in ambiente.queixa([])


def test_it_leans_on_nothing_that_could_be_missing():
    """`main.py` chama isto justamente quando o PySide6 não importa.

    Uma dependência aqui dentro faria a conferência morrer pelo mesmo
    motivo que ela veio explicar.
    """
    arvore = ast.parse(Path(ambiente.__file__).read_text(encoding="utf-8"))
    usados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            usados.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            usados.add(no.module.split(".")[0])
    assert usados <= sys.stdlib_module_names


def test_the_entry_point_survives_a_missing_dependency(monkeypatch, capsys):
    """Sem console, um import quebrado some; com a caixa, ele fala."""
    import ctypes
    import main as entrada

    caixa = []
    monkeypatch.setattr(
        ctypes.windll.user32,
        "MessageBoxW",
        lambda _janela, texto, titulo, _flags: caixa.append((titulo, texto)),
    )
    monkeypatch.setitem(sys.modules, "lolqueue.__main__", None)

    assert entrada.main() == 1
    assert caixa and "instalar.ps1" in caixa[0][1]
    assert "instalar.ps1" in capsys.readouterr().err
