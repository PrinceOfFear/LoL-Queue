"""Grava o repositorio GitHub e a chave publica no build antes de empacotar.

Exemplo:
    py -3 tools/preparar_atualizador.py --repositorio dono/LoL-Queue --publica BASE64URL
    powershell -ExecutionPolicy Bypass -File tools/build.ps1
    py -3 tools/preparar_atualizador.py --limpar

Somente a chave publica entra no app. A privada assina o manifesto de cada
release e deve continuar fora do repositorio, em chaves-atualizacao/.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lolqueue.atualizacao import GithubReleaseClient, UpdateIntegrityError, _public_key


ALVO = RAIZ / "lolqueue" / "atualizacao_embutida.py"
CONSTANTES = ("REPOSITORIO", "CHAVE_PUBLICA")


def _literal(value: str) -> str:
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise SystemExit("Repositorio e chave publica precisam ser ASCII simples.")
    return json.dumps(value)


def _write(path: Path, repository: str, public_key: str) -> None:
    raw = path.read_text(encoding="utf-8")
    values = {"REPOSITORIO": repository, "CHAVE_PUBLICA": public_key}
    for name in CONSTANTES:
        pattern = re.compile(rf"(?m)^{name}[ \t]*=[^\r\n]*$")
        replacement = f"{name} = {_literal(values[name])}"
        raw, count = pattern.subn(replacement, raw, count=1)
        if count != 1:
            raise SystemExit(f"Nao encontrei uma unica linha {name} = em {path}")
    path.write_text(raw, encoding="utf-8")


def _read_constants(path: Path) -> dict[str, str]:
    """Lê somente literais das duas constantes, sem executar o arquivo."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise SystemExit(f"Nao consegui ler a configuracao: {exc}") from exc
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        try:
            literal = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            continue
        if not isinstance(literal, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in CONSTANTES:
                values[target.id] = literal
    missing = [name for name in CONSTANTES if name not in values]
    if missing:
        raise SystemExit(f"Configuracao sem literais validas: {', '.join(missing)}")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configura o atualizador GitHub no proximo build.")
    parser.add_argument("--repositorio", help="dono/repositorio publico no GitHub")
    parser.add_argument("--publica", help="chave Ed25519 publica em base64url")
    parser.add_argument("--limpar", action="store_true", help="devolve o arquivo ao estado inativo")
    parser.add_argument("--ver", action="store_true", help="mostra a configuracao atual")
    parser.add_argument("--arquivo", default=str(ALVO))
    args = parser.parse_args(argv)
    target = Path(args.arquivo).expanduser().resolve()
    if not target.is_file():
        raise SystemExit(f"Nao achei {target}")
    if args.ver:
        values = _read_constants(target)
        repo = values["REPOSITORIO"]
        key = values["CHAVE_PUBLICA"]
        print(f"repositorio: {repo or '(vazio)'}")
        print(f"chave publica: {'configurada' if key else '(vazia)'}")
        return 0
    if args.limpar:
        if args.repositorio or args.publica:
            raise SystemExit("--limpar nao combina com --repositorio/--publica")
        repo, key = "", ""
    else:
        if not args.repositorio or not args.publica:
            raise SystemExit("Informe --repositorio e --publica juntos, ou use --limpar.")
        repo, key = args.repositorio.strip(), args.publica.strip()
        if not GithubReleaseClient(repository=repo, public_key=key).configured:
            raise SystemExit("Repositorio invalido; use exatamente dono/repositorio.")
        try:
            _public_key(key)
        except UpdateIntegrityError as exc:
            raise SystemExit(f"Chave publica invalida: {exc}") from exc
    _write(target, repo, key)
    print("Atualizador configurado para o proximo build." if repo else "Atualizador devolvido ao estado inativo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
