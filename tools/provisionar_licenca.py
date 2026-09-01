"""Provisiona uma chave no banco do servidor sem expor a chave privada.

Uso operacional (no host do servidor):
    py -3 tools/provisionar_licenca.py --dias 0 --assinatura-id UUID

Com ``--dias 0`` a chave fica aguardando o primeiro webhook pago. Para uma
concessao manual use um prazo curto e registre o motivo fora do repositorio.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from servidor.config import Settings
from servidor.db import LicenseStore, agora_iso, normalizar_chave


def _nova_chave() -> str:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "LQ-" + "-".join(
        "".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cadastra uma chave de licenca no banco")
    parser.add_argument("--chave", default="", help="LQ-XXXX-XXXX-XXXX; se vazio, sorteia")
    parser.add_argument("--dias", type=int, default=0, help="validade inicial; 0 aguarda webhook")
    parser.add_argument("--email", default="", help="email do assinante, sem segredo")
    parser.add_argument("--assinatura-id", default="", help="merchantSubscriptionId do PicPay")
    args = parser.parse_args(argv)
    if args.dias < 0:
        raise SystemExit("ERRO: --dias nao pode ser negativo")
    key = normalizar_chave(args.chave) if args.chave else _nova_chave()
    settings = Settings.from_env()
    paid_until = int(time.time()) + args.dias * 86400 if args.dias else 0
    LicenseStore(settings.database).provision(
        key,
        paid_until=paid_until,
        email=args.email.strip().lower(),
        provider_subscription_id=args.assinatura_id.strip(),
        now=agora_iso(),
    )
    print(key)
    if args.dias:
        print(f"validade inicial: {args.dias} dias")
    else:
        print("aguardando webhook de pagamento")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
