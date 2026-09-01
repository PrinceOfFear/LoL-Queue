"""Grava o servidor e a chave pública dentro do app, antes de empacotar.

Por que existe: `lolqueue/licenca/embutido.py` vive vazio no repositório
de propósito. Com os dois valores em branco a trava fica **inerte** — o
app abre como sempre abriu, sem tela de ativação e sem rede. Esse é o
padrão seguro: build errado gera um app que funciona, não um app que
não abre.

A consequência é direta: **empacotar sem rodar este script gera um
executável com a trava DESLIGADA**. Ele funciona, roda tudo, e não pede
licença de ninguém. Ótimo para você testar, péssimo para vender. Antes
de gerar o .exe que vai para o cliente, rode este script; depois de
gerar, rode `--limpar` para o repositório voltar ao estado de sempre.

O script mexe em exatamente duas linhas do arquivo (`SERVIDOR = ...` e
`CHAVE_PUBLICA = ...`), preservando todo o resto — comentários, docstring
e o tipo de quebra de linha original. Depois de gravar, ele relê o
arquivo do disco e confirma que `configurado()` virou o que deveria.

Uso:
    py -3 tools/preparar_build.py --servidor https://SEU-SERVIDOR --publica BASE64
    py -3 tools/preparar_build.py --limpar
    py -3 tools/preparar_build.py --ver
"""

from __future__ import annotations

import argparse
import base64
import binascii
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

#: Arquivo que este script edita.
ALVO = RAIZ / "lolqueue" / "licenca" / "embutido.py"

#: Nomes das duas constantes. `^` com re.M garante que `VAR_SERVIDOR`,
#: que também termina em SERVIDOR, não seja confundido com `SERVIDOR`.
CONSTANTES = ("SERVIDOR", "CHAVE_PUBLICA")


def validar_producao(servidor: str, publica: str) -> None:
    """Recusa configuracao que faria o build falhar fechado ou sem assinatura."""
    parsed = urlsplit(servidor)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit(
            "ERRO: --servidor precisa ser uma URL HTTPS sem credenciais, query ou fragmento."
        )
    try:
        raw = publica.encode("ascii")
        padding = b"=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.urlsafe_b64decode(raw + padding)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise SystemExit("ERRO: --publica nao e uma chave base64url valida.") from exc
    if len(decoded) != 32:
        raise SystemExit("ERRO: --publica precisa codificar exatamente 32 bytes Ed25519.")


def _padrao(nome: str) -> re.Pattern[bytes]:
    return re.compile(rb"(?m)^" + nome.encode("ascii") + rb"[ \t]*=[^\r\n]*")


def _quebra(bruto: bytes) -> bytes:
    """Descobre a quebra de linha dominante do arquivo, em bytes."""
    crlf = bruto.count(b"\r\n")
    lf_sozinho = bruto.count(b"\n") - crlf
    return b"\r\n" if crlf > lf_sozinho else b"\n"


def _literal(valor: str) -> str:
    """Transforma o valor num literal Python seguro, ou recusa."""
    if any(ord(c) < 32 or ord(c) > 126 for c in valor):
        raise SystemExit(
            f"ERRO: valor com caractere fora do ASCII imprimível: {valor!r}\n"
            "Servidor e chave pública são texto simples; se apareceu acento ou "
            "quebra de linha aí, o valor foi copiado errado."
        )
    return json.dumps(valor)


def escrever(alvo: Path, *, servidor: str, publica: str) -> None:
    """Reescreve as duas linhas do arquivo, preservando o resto byte a byte."""
    bruto = alvo.read_bytes()
    fim = _quebra(bruto)
    novos = {"SERVIDOR": servidor, "CHAVE_PUBLICA": publica}

    for nome in CONSTANTES:
        padrao = _padrao(nome)
        achados = padrao.findall(bruto)
        if len(achados) != 1:
            raise SystemExit(
                f"ERRO: esperava exatamente 1 linha começando com '{nome} =' em\n"
                f"{alvo}, mas achei {len(achados)}.\n"
                "O arquivo mudou de formato; ajuste este script antes de gravar."
            )
        linha = f"{nome} = {_literal(novos[nome])}".encode("ascii")
        bruto = padrao.sub(lambda _m, novo=linha: novo, bruto, count=1)

    # newline="" para o Python não traduzir nada: a quebra que está nos
    # bytes é a quebra que vai para o disco.
    if fim == b"\r\n":
        pass  # já está nos bytes; nada a normalizar
    with open(alvo, "wb") as saida:
        saida.write(bruto)


def ler(alvo: Path) -> tuple[str, str, bool]:
    """Importa o arquivo do disco e devolve (servidor, pública, configurado).

    As variáveis de ambiente têm prioridade sobre as constantes gravadas,
    então elas são tiradas do caminho durante a conferência. Sem isso, um
    `LOLQUEUE_LICENCA_SERVIDOR` esquecido no shell faria o script jurar
    que gravou o que não gravou — ou que limpou o que não limpou.
    """
    mod = _importar(alvo)
    variaveis = (mod.VAR_SERVIDOR, mod.VAR_CHAVE)
    salvo = {v: os.environ.pop(v) for v in variaveis if v in os.environ}
    try:
        mod = _importar(alvo)
        return mod.servidor(), mod.chave_publica(), mod.configurado()
    finally:
        os.environ.update(salvo)


def _importar(alvo: Path):
    """Carrega o arquivo como módulo avulso, sem passar pelo cache de import."""
    spec = importlib.util.spec_from_file_location("_embutido_conferencia", alvo)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERRO: não consegui importar {alvo}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="preparar_build.py",
        description=(
            "Grava (ou apaga) o endereço do servidor e a chave pública dentro "
            "de lolqueue/licenca/embutido.py, antes de empacotar o executável."
        ),
        epilog=(
            "Empacotar SEM rodar este script gera um .exe com a trava\n"
            "desligada: ele abre para qualquer um, sem pedir licença. Esse é o\n"
            "padrão seguro do projeto, mas não é o que você quer vender.\n"
            "\n"
            "Fluxo normal:\n"
            "  py -3 tools/preparar_build.py --servidor https://... --publica ...\n"
            "  powershell -ExecutionPolicy Bypass -File tools/build.ps1\n"
            "  py -3 tools/preparar_build.py --limpar\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--servidor", default=None, help="URL do servidor, sem barra no fim")
    p.add_argument("--publica", default=None, help="chave pública Ed25519 em base64url")
    p.add_argument(
        "--limpar",
        action="store_true",
        help="devolve as duas constantes para \"\" (trava inerte de novo)",
    )
    p.add_argument("--ver", action="store_true", help="só mostra o que está gravado")
    p.add_argument(
        "--arquivo",
        default=str(ALVO),
        help=f"arquivo a editar (padrão: {ALVO})",
    )
    args = p.parse_args(argv)

    alvo = Path(args.arquivo).expanduser().resolve()
    if not alvo.is_file():
        raise SystemExit(f"ERRO: não achei {alvo}")

    if args.ver:
        servidor, publica, ligado = ler(alvo)
        print(f"arquivo   : {alvo}")
        print(f"servidor  : {servidor or '(vazio)'}")
        print(f"pública   : {publica or '(vazio)'}")
        print(f"trava     : {'LIGADA' if ligado else 'inerte'}")
        return 0

    if args.limpar:
        if args.servidor is not None or args.publica is not None:
            raise SystemExit("ERRO: --limpar não combina com --servidor/--publica.")
        alvo_servidor, alvo_publica = "", ""
    else:
        if not args.servidor or not args.publica:
            raise SystemExit(
                "ERRO: informe --servidor e --publica juntos, ou use --limpar.\n"
                "Gravar só metade deixaria a trava inerte do mesmo jeito."
            )
        alvo_servidor = args.servidor.strip().rstrip("/")
        alvo_publica = args.publica.strip()
        validar_producao(alvo_servidor, alvo_publica)

    escrever(alvo, servidor=alvo_servidor, publica=alvo_publica)

    # Releitura obrigatória: quem manda é o que está no disco, não o que
    # este processo acha que escreveu.
    servidor, publica, ligado = ler(alvo)
    esperado = bool(alvo_servidor and alvo_publica)
    if servidor != alvo_servidor or publica != alvo_publica or ligado != esperado:
        raise SystemExit(
            "ERRO: gravei mas a releitura não bate.\n"
            f"  esperava servidor={alvo_servidor!r} publica={alvo_publica!r} "
            f"configurado={esperado}\n"
            f"  li       servidor={servidor!r} publica={publica!r} "
            f"configurado={ligado}\n"
            f"Confira {alvo} na mão antes de empacotar."
        )

    if args.limpar:
        print(f"Limpo: {alvo}")
        print("Trava inerte de novo. Um build feito agora abre sem pedir licença.")
    else:
        print(f"Gravado em {alvo}")
        print(f"  servidor : {servidor}")
        print(f"  pública  : {publica}")
        print("Trava LIGADA. Empacote agora e rode --limpar depois.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
