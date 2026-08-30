"""Onde o servidor e a chave pública são gravados na hora de empacotar.

Vazio no repositório de propósito. Rodando do fonte, sem nada aqui e
sem variável de ambiente, a porta fica **inerte**: o app abre como
sempre abriu, sem tela de ativação, sem rede, sem risco de um servidor
fora do ar impedir alguém de jogar. Só o executável distribuído leva
esses dois valores gravados, por `tools/preparar_build.py`.

Isso é decisão de projeto, não descuido: a alternativa — a trava ligada
por padrão — significa que qualquer erro de configuração, queda de
servidor ou build feito sem as variáveis certas transforma um app que
funcionava num app que não abre.

As variáveis de ambiente têm prioridade sobre o que está gravado aqui,
para dar para testar a trava inteira apontando para um servidor local
sem tocar em nenhum arquivo.
"""

from __future__ import annotations

import os

#: Endereço do servidor de licenças, sem barra no fim.
#: Ex.: "https://licencas.seudominio.com"
SERVIDOR = ""

#: Chave pública Ed25519 em base64url, gerada por `tools/gerar_chaves.py`.
#: A privada correspondente fica só com o dono do servidor.
CHAVE_PUBLICA = ""

VAR_SERVIDOR = "LOLQUEUE_LICENCA_SERVIDOR"
VAR_CHAVE = "LOLQUEUE_LICENCA_CHAVE"


def servidor() -> str:
    return (os.environ.get(VAR_SERVIDOR) or SERVIDOR).strip().rstrip("/")


def chave_publica() -> str:
    return (os.environ.get(VAR_CHAVE) or CHAVE_PUBLICA).strip()


def configurado() -> bool:
    """A trava só liga com endereço **e** chave pública.

    Com endereço e sem chave o app não teria como conferir assinatura
    nenhuma: aceitaria qualquer texto como licença, o que é pior do que
    não ter trava. Faltando qualquer um dos dois, a porta fica aberta.
    """
    return bool(servidor() and chave_publica())
