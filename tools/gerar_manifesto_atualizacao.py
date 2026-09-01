"""Cria o manifesto assinado que acompanha uma GitHub Release.

O manifesto conecta, por assinatura Ed25519, a versao e os dois ZIPs que o
aplicativo pode instalar. Sem ele, o cliente recusa a release mesmo que o ZIP
esteja hospedado no repositorio correto.

Exemplo:
    py -3 tools/gerar_manifesto_atualizacao.py \
      --standalone "Distribuicao/LoL-Queue-0.1.2-win64.zip" \
      --python "Distribuicao/LoL-Queue-0.1.2-instalacao-python.zip" \
      --chave-privada chaves-atualizacao/release.chave-privada
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lolqueue.atualizacao import UPDATE_SCHEMA, canonical_manifest, sign_manifest
from lolqueue.version import VERSION


def _root_of(bundle: Path, entry: str) -> str:
    """Confere que o ZIP tem uma unica pasta raiz e o ponto de entrada certo."""

    try:
        with zipfile.ZipFile(bundle) as archive:
            # `Compress-Archive` no Windows usa barra invertida dentro do ZIP.
            # Converte antes da conferência para aplicar exatamente as mesmas
            # regras que o cliente usará ao extrair a atualização.
            names = [
                PurePosixPath(info.filename.replace("\\", "/"))
                for info in archive.infolist()
                if info.filename
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"ZIP invalido: {bundle} ({exc})") from exc
    roots = {path.parts[0] for path in names if path.parts and not path.is_absolute()}
    if len(roots) != 1 or any(
        ".." in path.parts
        or path.is_absolute()
        or any(":" in part for part in path.parts)
        for path in names
    ):
        raise SystemExit(f"{bundle} precisa ter uma unica pasta raiz segura.")
    root = roots.pop()
    if not any(path == PurePosixPath(root, entry) for path in names):
        raise SystemExit(f"{bundle} nao contem {root}/{entry}.")
    return root


def _artifact(bundle: Path, entry: str) -> dict[str, object]:
    if not bundle.is_file():
        raise SystemExit(f"Nao achei {bundle}")
    size = bundle.stat().st_size
    if size <= 0:
        raise SystemExit(f"{bundle} esta vazio")
    return {
        "file": bundle.name,
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "size": size,
        "root": _root_of(bundle, entry),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera manifesto assinado de atualizacao.")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--standalone", required=True, help="ZIP win64 criado por tools/build.ps1")
    parser.add_argument("--python", required=True, help="ZIP de instalacao Python criado por tools/build.ps1")
    parser.add_argument("--chave-privada", required=True, help="arquivo secreto Ed25519")
    parser.add_argument("--notas", default="", help="arquivo UTF-8 com notas da release")
    parser.add_argument("--saida", default=str(RAIZ / "Distribuicao" / "lolqueue-update.json"))
    args = parser.parse_args(argv)
    private_path = Path(args.chave_privada).expanduser().resolve()
    if not private_path.is_file():
        raise SystemExit(f"Nao achei a chave privada: {private_path}")
    notes = ""
    if args.notas:
        try:
            notes = Path(args.notas).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SystemExit(f"Nao consegui ler as notas: {exc}") from exc
    data = {
        "schema": UPDATE_SCHEMA,
        "version": args.version,
        "notes": notes,
        "artifacts": {
            "standalone": _artifact(Path(args.standalone).expanduser().resolve(), "LoL Queue.exe"),
            "python": _artifact(Path(args.python).expanduser().resolve(), "main.py"),
        },
    }
    raw = canonical_manifest(data)
    signature = sign_manifest(raw, private_path.read_text(encoding="ascii").strip())
    output = Path(args.saida).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    signature_path = output.with_name(output.name + ".sig")
    signature_path.write_text(signature + "\n", encoding="ascii")
    print(f"Manifesto: {output}")
    print(f"Assinatura: {signature_path}")
    print("Envie os dois junto dos ZIPs para a mesma GitHub Release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
