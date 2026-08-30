"""Formato da licença: um bilhete assinado que vale sozinho, sem servidor.

Este módulo é o único lugar onde o formato existe. O app e o servidor
importam daqui os dois — se o formato fosse escrito duas vezes, uma
mudança de um lado geraria licenças que o outro lado recusa em silêncio,
e o usuário veria "licença inválida" sem nada explicando por quê.

Por que assinatura e não um segredo compartilhado: o app precisa
continuar funcionando alguns dias sem internet, então ele tem que
conseguir conferir a licença sozinho. Com HMAC isso exigiria enfiar o
segredo dentro do executável — e quem tem o segredo emite licença.
Com Ed25519 o executável carrega só a chave pública: dá para conferir,
não dá para emitir.

O bilhete tem três partes separadas por ponto:

    LQ1.<carga em base64url>.<assinatura em base64url>

A versão entra no que é assinado de propósito. Sem isso alguém poderia
reaproveitar a assinatura de uma carga num formato futuro diferente.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

#: Prefixo de versão do bilhete. Muda se o formato da carga mudar.
VERSAO = "LQ1"

#: Folga de relógio aceita na validade, em segundos. Relógio de usuário
#: erra por fuso mal configurado e por atraso de sincronização; recusar
#: uma licença boa por dois minutos de diferença seria pior do que dar
#: dois minutos de licença vencida.
FOLGA_RELOGIO = 300


class LicencaInvalida(Exception):
    """Bilhete que não serve: mal formado, assinatura errada ou vencido.

    Uma exceção só para os três casos porque quem chama trata os três do
    mesmo jeito — manda ativar de novo. A mensagem diz qual foi.
    """


@dataclass(frozen=True)
class Licenca:
    """O conteúdo do bilhete, já conferido.

    `expira` é o que trava o app; `assinatura_ate` é o fim real do plano
    pago e serve só para mostrar na tela. Os dois são diferentes porque
    o bilhete é curto de propósito: ele vale poucos dias e é renovado a
    cada conversa com o servidor. É isso que faz um cancelamento surtir
    efeito sem precisar que o app esteja online na hora certa.
    """

    chave: str
    maquina: str
    expira: int
    assinatura_ate: int
    emitido: int
    plano: str = ""
    apelido: str = ""
    extra: dict = field(default_factory=dict)

    def vencida(self, agora: float | None = None) -> bool:
        momento = time.time() if agora is None else agora
        return momento > self.expira + FOLGA_RELOGIO

    def serve_para(self, maquina: str) -> bool:
        """Bilhete sem máquina serve em qualquer uma (licença de dono)."""
        return not self.maquina or self.maquina == maquina

    def carga(self) -> dict:
        dados = {
            "chave": self.chave,
            "maquina": self.maquina,
            "expira": int(self.expira),
            "assinatura_ate": int(self.assinatura_ate),
            "emitido": int(self.emitido),
            "plano": self.plano,
            "apelido": self.apelido,
        }
        dados.update(self.extra)
        return dados


def _b64_grava(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _b64_le(texto: str) -> bytes:
    # base64url sem o preenchimento: o bilhete fica menor e sem "=" ele
    # atravessa URL e campo de texto sem ninguém escapar nada.
    resto = len(texto) % 4
    if resto:
        texto += "=" * (4 - resto)
    return base64.urlsafe_b64decode(texto.encode("ascii"))


def gerar_par() -> tuple[str, str]:
    """Um par novo: (privada, pública), ambas em base64url.

    A privada nunca entra no repositório nem no executável. Quem tem a
    privada emite licença; é o segredo do negócio inteiro.
    """
    privada = Ed25519PrivateKey.generate()
    bruta_privada = privada.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    bruta_publica = privada.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64_grava(bruta_privada), _b64_grava(bruta_publica)


def publica_de(privada_b64: str) -> str:
    """A pública correspondente a uma privada, para conferir um par."""
    chave = Ed25519PrivateKey.from_private_bytes(_b64_le(privada_b64))
    bruta = chave.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64_grava(bruta)


def assinar(licenca: Licenca, privada_b64: str) -> str:
    """Transforma a licença no bilhete de texto assinado.

    Só o servidor e as ferramentas de emissão chamam isto — o app não
    tem a chave privada para passar aqui.
    """
    try:
        chave = Ed25519PrivateKey.from_private_bytes(_b64_le(privada_b64))
    except (ValueError, TypeError) as erro:
        raise LicencaInvalida(f"chave privada inválida: {erro}") from erro
    carga = json.dumps(
        licenca.carga(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    cabeca = f"{VERSAO}.{_b64_grava(carga)}"
    assinatura = chave.sign(cabeca.encode("ascii"))
    return f"{cabeca}.{_b64_grava(assinatura)}"


def conferir(
    bilhete: str,
    publica_b64: str,
    *,
    maquina: str | None = None,
    agora: float | None = None,
) -> Licenca:
    """Devolve a licença se o bilhete for legítimo; levanta se não for.

    A ordem importa: assinatura primeiro, conteúdo depois. Ler campo de
    carga não assinada é confiar no que o atacante escreveu — mesmo só
    para decidir a mensagem de erro.
    """
    partes = bilhete.strip().split(".")
    if len(partes) != 3:
        raise LicencaInvalida("bilhete fora do formato")
    versao, carga_b64, assinatura_b64 = partes
    if versao != VERSAO:
        raise LicencaInvalida(f"versão desconhecida: {versao}")
    try:
        publica = Ed25519PublicKey.from_public_bytes(_b64_le(publica_b64))
    except (ValueError, TypeError) as erro:
        raise LicencaInvalida(f"chave pública inválida: {erro}") from erro
    try:
        publica.verify(
            _b64_le(assinatura_b64), f"{versao}.{carga_b64}".encode("ascii")
        )
    except (InvalidSignature, ValueError, TypeError) as erro:
        raise LicencaInvalida("assinatura não confere") from erro

    try:
        dados = json.loads(_b64_le(carga_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as erro:
        raise LicencaInvalida("carga ilegível") from erro
    if not isinstance(dados, dict):
        raise LicencaInvalida("carga não é um objeto")

    conhecidos = {
        "chave",
        "maquina",
        "expira",
        "assinatura_ate",
        "emitido",
        "plano",
        "apelido",
    }
    try:
        licenca = Licenca(
            chave=str(dados.get("chave", "")),
            maquina=str(dados.get("maquina", "")),
            expira=int(dados["expira"]),
            assinatura_ate=int(dados.get("assinatura_ate", dados["expira"])),
            emitido=int(dados.get("emitido", 0)),
            plano=str(dados.get("plano", "")),
            apelido=str(dados.get("apelido", "")),
            # Campo novo emitido por um servidor mais recente não pode
            # derrubar um app antigo: guarda e segue.
            extra={k: v for k, v in dados.items() if k not in conhecidos},
        )
    except (KeyError, TypeError, ValueError) as erro:
        raise LicencaInvalida(f"carga incompleta: {erro}") from erro

    if licenca.vencida(agora):
        raise LicencaInvalida("licença vencida")
    if maquina is not None and not licenca.serve_para(maquina):
        raise LicencaInvalida("licença emitida para outro computador")
    return licenca
