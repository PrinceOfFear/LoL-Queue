"""Emite um bilhete de licença assinado direto do disco, sem servidor.

Por que existe: é a saída de emergência. O servidor pode estar fora do
ar, a conta da hospedagem pode ter expirado, o banco pode ter sumido —
e mesmo assim o dono precisa conseguir destravar o próprio PC e atender
um cliente na mão. Este script assina um bilhete usando a chave privada
que está em `chaves-licenca/servidor.chave-privada`, imprime, e com
`--instalar` grava direto no estado local do app.

O bilhete que sai daqui é idêntico ao que o servidor emite: mesma
assinatura, mesmo formato. O app não sabe (nem precisa saber) a
diferença. O que **não** sai daqui é registro: o servidor não fica
sabendo dessa licença, então ela não conta slot, não aparece no /admin
e não dá para revogar. Use com parcimônia.

Uso:
    py -3 tools/emitir_licenca.py                        # esta máquina, 10 anos
    py -3 tools/emitir_licenca.py --instalar             # e já grava aqui
    py -3 tools/emitir_licenca.py --dias 30 --maquina abc123...
    py -3 tools/emitir_licenca.py --qualquer --dias 7    # PERIGO, veja --help
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lolqueue.licenca import chave as chave_mod
from lolqueue.licenca import estado as estado_mod
from lolqueue.licenca import maquina as maquina_mod

#: Onde `tools/gerar_chaves.py` deixa a chave privada.
PRIVADA_PADRAO = (
    Path(__file__).resolve().parent.parent / "chaves-licenca" / "servidor.chave-privada"
)

#: Dez anos. Uma licença emitida na mão é para durar; quem controla o
#: prazo de verdade é a renovação contra o servidor, quando ele existe.
DIAS_PADRAO = 30

#: Alfabeto sem 0/O e 1/I, para o cliente conseguir ditar a chave no telefone.
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def nova_chave() -> str:
    """Sorteia uma chave no formato LQ-XXXX-XXXX-XXXX."""
    grupos = [
        "".join(secrets.choice(ALFABETO) for _ in range(4)) for _ in range(3)
    ]
    return "LQ-" + "-".join(grupos)


def ler_privada(arquivo: Path) -> str:
    """Lê a chave privada do disco, com erro legível se não estiver lá."""
    try:
        bruto = arquivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(
            f"ERRO: não achei a chave privada em {arquivo}\n"
            "\n"
            "Gere o par uma vez com:  py -3 tools/gerar_chaves.py\n"
            "Ou aponte para outro arquivo com --privada CAMINHO."
        ) from None
    privada = bruto.strip()
    if not privada:
        raise SystemExit(f"ERRO: o arquivo {arquivo} está vazio.")
    return privada


def emitir(
    *,
    privada: str,
    chave: str,
    maquina: str,
    dias: int,
    plano: str = "",
    apelido: str = "",
    agora: float | None = None,
) -> tuple[str, chave_mod.Licenca]:
    """Monta e assina a licença. Devolve (bilhete, licença)."""
    inicio = int(agora if agora is not None else time.time())
    fim = inicio + dias * 86400
    licenca = chave_mod.Licenca(
        chave=chave,
        maquina=maquina,
        # Os dois prazos andam juntos aqui de propósito: um bilhete de
        # emergência que vencesse na janela curta de folga offline
        # deixaria de servir em uma semana, que é justamente quando o
        # servidor ainda está fora do ar.
        expira=fim,
        assinatura_ate=fim,
        emitido=inicio,
        plano=plano,
        apelido=apelido,
        extra={"origem": "emitir_licenca.py"},
    )
    return chave_mod.assinar(licenca, privada), licenca


def instalar(bilhete: str, chave: str, *, agora: float | None = None) -> Path:
    """Grava o bilhete no estado local do app. Devolve o caminho do arquivo."""
    momento = agora if agora is not None else time.time()
    est = estado_mod.Estado.load()
    est.bilhete = bilhete
    est.chave = chave
    est.validado_em = momento
    est.marcar_relogio(momento)
    est.mensagem = ""
    est.save()
    return estado_mod.caminho()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="emitir_licenca.py",
        description=(
            "Emite um bilhete de licença assinado, sem passar pelo servidor. "
            "Saída de emergência: serve para destravar o seu próprio PC com o "
            "servidor fora do ar e para atender um cliente na mão."
        ),
        epilog=(
            "AVISO SOBRE --qualquer\n"
            "  Um bilhete emitido com --qualquer nao tem maquina amarrada: ele\n"
            "  destrava QUALQUER COMPUTADOR DO MUNDO em que for colado, e vale\n"
            "  ate a data de expiracao, sem depender do servidor.\n"
            "  Ele existe para teste seu, em maquina sua. NUNCA mande esse\n"
            "  bilhete para um cliente, nunca cole em suporte, nunca guarde em\n"
            "  lugar sincronizado: quem tiver o texto entra de graca, e a unica\n"
            "  forma de matar o bilhete e trocar o par de chaves (o que derruba\n"
            "  todas as outras licencas junto).\n"
            "  Prefira sempre --dias curto quando usar --qualquer.\n"
            "\n"
            "Bilhetes emitidos aqui nao passam pelo servidor: nao ocupam slot,\n"
            "nao aparecem no /admin e nao podem ser revogados."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--chave",
        default="",
        help="chave do cliente (LQ-XXXX-XXXX-XXXX). Sem isso, sorteia uma nova.",
    )
    p.add_argument(
        "--dias",
        type=int,
        default=DIAS_PADRAO,
        help=f"validade em dias (padrão: {DIAS_PADRAO})",
    )
    p.add_argument(
        "--maquina",
        default="",
        help=(
            "impressão da máquina em hex. Padrão: esta máquina. "
            "O cliente vê a dele na tela de ativação do app."
        ),
    )
    p.add_argument(
        "--qualquer",
        action="store_true",
        help=(
            "PERIGO: emite sem amarrar em máquina nenhuma. O bilhete passa a "
            "valer em qualquer computador do mundo e não deve ser distribuído. "
            "Veja o aviso no fim desta ajuda."
        ),
    )
    p.add_argument("--plano", default="", help="rótulo do plano (aparece no app)")
    p.add_argument("--apelido", default="", help="nome do cliente, só para você lembrar")
    p.add_argument(
        "--privada",
        default=str(PRIVADA_PADRAO),
        help=f"arquivo da chave privada (padrão: {PRIVADA_PADRAO})",
    )
    p.add_argument(
        "--instalar",
        action="store_true",
        help="além de imprimir, grava o bilhete no estado local deste PC",
    )
    args = p.parse_args(argv)

    if args.dias <= 0:
        raise SystemExit("ERRO: --dias tem que ser maior que zero.")
    if args.dias > 31 and os.environ.get("LOLQUEUE_ALLOW_LONG_LICENSE") != "1":
        raise SystemExit(
            "ERRO: licencas manuais acima de 31 dias exigem "
            "LOLQUEUE_ALLOW_LONG_LICENSE=1 no host do operador."
        )
    if args.qualquer and args.maquina:
        raise SystemExit("ERRO: --qualquer e --maquina são mutuamente exclusivos.")

    privada = ler_privada(Path(args.privada).expanduser())
    publica = chave_mod.publica_de(privada)

    if args.qualquer and os.environ.get("LOLQUEUE_ALLOW_UNBOUND_LICENSE") != "1":
        raise SystemExit(
            "ERRO: uma licenca sem computador e proibida por padrao; "
            "habilite LOLQUEUE_ALLOW_UNBOUND_LICENSE=1 somente em desenvolvimento."
        )
    if args.qualquer and args.dias > 7:
        raise SystemExit("ERRO: licenca universal de desenvolvimento pode durar no maximo 7 dias.")

    if args.qualquer:
        alvo = ""
    elif args.maquina:
        alvo = args.maquina.strip().lower()
    else:
        alvo = maquina_mod.impressao()

    chave_cli = args.chave.strip().upper() or nova_chave()
    bilhete, licenca = emitir(
        privada=privada,
        chave=chave_cli,
        maquina=alvo,
        dias=args.dias,
        plano=args.plano,
        apelido=args.apelido,
    )

    # Conferir antes de entregar: se o bilhete não passar na mesma
    # verificação que o app faz, é melhor descobrir agora do que no PC
    # do cliente.
    chave_mod.conferir(bilhete, publica, maquina=alvo or None)

    barra = "=" * 68
    validade = time.strftime("%d/%m/%Y", time.localtime(licenca.expira))
    print(barra)
    print("BILHETE EMITIDO")
    print(barra)
    print(f"  chave    : {licenca.chave}")
    print(f"  máquina  : {alvo or '(QUALQUER COMPUTADOR)'}")
    print(f"  validade : {args.dias} dias, até {validade}")
    if licenca.plano:
        print(f"  plano    : {licenca.plano}")
    if licenca.apelido:
        print(f"  apelido  : {licenca.apelido}")
    print()
    print(bilhete)
    print()
    if not alvo:
        print("!! ESTE BILHETE DESTRAVA QUALQUER COMPUTADOR. NÃO DISTRIBUA. !!")
        print()

    if args.instalar:
        destino = instalar(bilhete, licenca.chave)
        print(f"Instalado em: {destino}")
    else:
        print("Para usar neste PC agora, rode de novo com --instalar.")
    print(barra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
