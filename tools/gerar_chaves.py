"""Gera o par de chaves Ed25519 que sustenta o licenciamento inteiro.

Por que existe: todo bilhete de licença é assinado com a chave privada e
conferido com a pública. A privada mora só no servidor; a pública é
gravada dentro do executável por `tools/preparar_build.py`. Sem esse par
não há licença nenhuma para emitir nem para conferir.

Roda uma vez na vida do produto. As duas metades têm destinos opostos:

  privada  -> `chaves-licenca/servidor.chave-privada` (nunca sai daqui,
              nunca vai para o git, vira segredo do servidor)
  pública  -> impressa na tela, para colar no `preparar_build.py`

Perder a privada mata **todas** as licenças já emitidas de uma vez: os
bilhetes antigos continuam assinados por uma chave que ninguém mais tem,
e um par novo não confere nenhum deles. Por isso o script se recusa a
sobrescrever um par existente sem `--forcar`.

Uso:
    py -3 tools/gerar_chaves.py
    py -3 tools/gerar_chaves.py --forcar        # sobrescreve (irreversível)
    py -3 tools/gerar_chaves.py --pasta C:/tmp  # grava em outro lugar
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lolqueue.licenca import chave as chave_mod

#: Pasta padrão do par de chaves. Já está no `.gitignore`.
PASTA = Path(__file__).resolve().parent.parent / "chaves-licenca"

NOME_PRIVADA = "servidor.chave-privada"
NOME_PUBLICA = "servidor.chave-publica"


def restringir(arquivo: Path) -> str:
    """Tenta deixar o arquivo legível só pelo dono. Devolve o que fez.

    No Windows `os.chmod` só mexe no atributo somente-leitura, que não
    protege nada; quem faz o serviço é o `icacls`. Se falhar, não é
    motivo para abortar — a chave já está gravada, e avisar é melhor do
    que apagar o trabalho.
    """
    if os.name == "nt":
        usuario = os.environ.get("USERNAME") or ""
        if not usuario:
            return "permissão não ajustada (USERNAME vazio)"
        try:
            subprocess.run(
                ["icacls", str(arquivo), "/inheritance:r", "/grant:r", f"{usuario}:F"],
                check=True,
                capture_output=True,
                timeout=20,
            )
        except Exception as erro:  # noqa: BLE001 - qualquer falha aqui é só aviso
            return f"permissão não ajustada ({erro.__class__.__name__})"
        return f"acesso restrito a {usuario}"
    try:
        os.chmod(arquivo, 0o600)
    except OSError as erro:
        return f"permissão não ajustada ({erro})"
    return "modo 0600"


def gerar(pasta: Path, *, forcar: bool) -> tuple[str, str, str]:
    """Grava o par em `pasta` e devolve (privada, pública, nota de permissão)."""
    privada_arq = pasta / NOME_PRIVADA
    publica_arq = pasta / NOME_PUBLICA

    if privada_arq.exists() and not forcar:
        raise SystemExit(
            f"ERRO: já existe uma chave privada em {privada_arq}\n"
            "\n"
            "Sobrescrever essa chave invalida TODAS as licenças já emitidas,\n"
            "de uma vez só, e não há como voltar atrás: os bilhetes antigos\n"
            "ficam assinados por uma chave que ninguém mais tem.\n"
            "\n"
            "Se é isso mesmo que você quer, faça uma cópia do arquivo antigo\n"
            "e rode de novo com --forcar."
        )

    privada, publica = chave_mod.gerar_par()

    pasta.mkdir(parents=True, exist_ok=True)
    privada_arq.write_text(privada + "\n", encoding="utf-8")
    nota = restringir(privada_arq)
    publica_arq.write_text(publica + "\n", encoding="utf-8")
    return privada, publica, nota


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="gerar_chaves.py",
        description=(
            "Gera o par Ed25519 do licenciamento. A privada é gravada em "
            "chaves-licenca/ (fora do git) e a pública é impressa na tela."
        ),
        epilog=(
            "CUIDADO: gerar um par novo por cima do antigo invalida todas as "
            "licencas ja emitidas. Sem --forcar o script se recusa a fazer isso."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "sobrescreve um par existente. IRREVERSÍVEL: todas as licenças "
            "assinadas com a chave antiga param de valer."
        ),
    )
    p.add_argument(
        "--pasta",
        default=str(PASTA),
        help=f"onde gravar o par (padrão: {PASTA})",
    )
    args = p.parse_args(argv)

    pasta = Path(args.pasta).expanduser().resolve()
    _privada, publica, nota = gerar(pasta, forcar=args.forcar)

    barra = "=" * 68
    print(barra)
    print("PAR DE CHAVES GERADO")
    print(barra)
    print()
    print("1) CHAVE PRIVADA  -- segredo do servidor, nunca compartilhe")
    print(f"   gravada em: {pasta / NOME_PRIVADA}")
    print(f"   permissão:  {nota}")
    print("   -> vai para o servidor na variável LICENCA_PRIVADA")
    print("      (Fly.io: fly secrets set LICENCA_PRIVADA=\"...\")")
    print("   -> faça UMA cópia de segurança offline. Se perder este arquivo,")
    print("      todas as licenças já emitidas morrem junto.")
    print("   -> se vazar, qualquer pessoa passa a emitir licença de graça.")
    print()
    print("2) CHAVE PÚBLICA  -- pode aparecer em qualquer lugar")
    print(f"   também gravada em: {pasta / NOME_PUBLICA}")
    print()
    print(f"   {publica}")
    print()
    print("   -> entra no executável antes de empacotar:")
    print("      py -3 tools/preparar_build.py --servidor https://SEU-SERVIDOR \\")
    print(f"                                   --publica {publica}")
    print()
    print(barra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
