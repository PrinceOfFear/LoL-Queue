"""Gera a chave Ed25519 exclusiva que assina releases do LoL Queue.

Uso:
    py -3 tools/gerar_chaves_atualizacao.py

A chave privada fica em ``chaves-atualizacao/`` (ignorada pelo Git) e nunca
deve ser enviada ao GitHub, a usuarios ou junto do aplicativo. A publica e a
unica parte que entra no build por ``preparar_atualizador.py``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lolqueue.atualizacao import generate_keypair


PASTA = RAIZ / "chaves-atualizacao"
PRIVADA = "release.chave-privada"
PUBLICA = "release.chave-publica"


def _restringir(path: Path) -> str:
    """Tenta restringir a privada ao usuario atual sem apagar se falhar."""

    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
            return "modo 0600"
        except OSError as exc:
            return f"permissao nao ajustada ({exc})"
    user = os.environ.get("USERNAME", "")
    if not user:
        return "permissao nao ajustada (USERNAME vazio)"
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            check=True,
            capture_output=True,
            timeout=20,
        )
        return f"acesso restrito a {user}"
    except Exception as exc:  # a chave continua gravada, entao e aviso
        return f"permissao nao ajustada ({exc.__class__.__name__})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera chaves para assinar atualizacoes.")
    parser.add_argument("--pasta", default=str(PASTA))
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="sobrescreve uma chave existente; invalida a confianca dos builds antigos",
    )
    args = parser.parse_args(argv)
    folder = Path(args.pasta).expanduser().resolve()
    private_file, public_file = folder / PRIVADA, folder / PUBLICA
    if private_file.exists() and not args.forcar:
        raise SystemExit(
            f"Ja existe uma chave privada em {private_file}.\n"
            "Nao a sobrescreva: builds antigos deixariam de confiar em releases novas."
        )
    private, public = generate_keypair()
    folder.mkdir(parents=True, exist_ok=True)
    private_file.write_text(private + "\n", encoding="ascii")
    note = _restringir(private_file)
    public_file.write_text(public + "\n", encoding="ascii")
    print("Chave de atualizacao criada.")
    print(f"Privada (NAO compartilhe): {private_file}")
    print(f"Permissao: {note}")
    print(f"Publica: {public_file}")
    print("Configure o build com tools/preparar_atualizador.py usando a chave publica.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
