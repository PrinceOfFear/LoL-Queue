"""Assina os arquivos de uma distribuicao do LoL Queue.

Uso:
    py -3 tools/gerar_manifesto_integridade.py \
        --pasta "Distribuicao\\LoL Queue" \
        --version 0.2.1 \
        --chave-privada chaves-atualizacao\\release.chave-privada

A chave privada so e lida localmente para criar ``lolqueue-integrity.json`` e
``lolqueue-integrity.json.sig``. Somente esses dois arquivos seguem para o
usuario; a chave privada nunca entra no pacote.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lolqueue.seguranca import IntegrityError, write_signed_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera o selo Ed25519 de integridade de uma distribuicao."
    )
    parser.add_argument("--pasta", required=True, help="pasta raiz do pacote pronto")
    parser.add_argument("--version", required=True, help="versao que sera registrada no selo")
    parser.add_argument(
        "--chave-privada", required=True, help="arquivo local da chave Ed25519 privada"
    )
    args = parser.parse_args(argv)

    root = Path(args.pasta).expanduser().resolve()
    private_path = Path(args.chave_privada).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Nao achei a pasta de distribuicao: {root}")
    if not private_path.is_file():
        raise SystemExit(f"Nao achei a chave privada: {private_path}")
    try:
        private_key = private_path.read_text(encoding="ascii").strip()
        manifest, signature = write_signed_manifest(root, args.version, private_key)
    except (OSError, IntegrityError) as exc:
        raise SystemExit(f"Nao consegui assinar a distribuicao: {exc}") from exc

    print("Selo de integridade criado.")
    print(f"Manifesto: {manifest}")
    print(f"Assinatura: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
