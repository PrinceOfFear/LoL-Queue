"""Configuracao publica do atualizador remoto.

Fica vazia no repositorio por seguranca operacional: sem repositorio oficial
e chave publica, a interface informa que a atualizacao ainda nao esta pronta,
em vez de baixar de um lugar indefinido. Configure antes do build com
``tools/preparar_atualizador.py``.
"""

from __future__ import annotations

import os

# Exemplo: "seu-usuario/LoL-Queue"
REPOSITORIO = "PrinceOfFear/LoL-Queue"

# Chave Ed25519 publica em base64url. A privada nunca entra no app.
CHAVE_PUBLICA = "gybMdk-fWF5pnazfD7EccMaxJ1gYsEnUn0tsjqE8tQE"

# Somente para teste local; o build publico deve levar os valores acima.
VAR_REPOSITORIO = "LOLQUEUE_ATUALIZACAO_REPOSITORIO"
VAR_CHAVE = "LOLQUEUE_ATUALIZACAO_CHAVE"


def repositorio() -> str:
    # A chave e o repositorio gravados no build sao a ancora de confianca.
    # Uma variavel de ambiente pode ser alterada por um atalho, um .bat ou
    # outro processo do mesmo usuario; deixa-la sobrescrever um build oficial
    # permitiria trocar os dois por um repositorio/chave de terceiro. O
    # fallback continua util para testar o codigo-fonte, que nasce inativo.
    return (REPOSITORIO or os.environ.get(VAR_REPOSITORIO) or "").strip()


def chave_publica() -> str:
    return (CHAVE_PUBLICA or os.environ.get(VAR_CHAVE) or "").strip()


def configurado() -> bool:
    return bool(repositorio() and chave_publica())
