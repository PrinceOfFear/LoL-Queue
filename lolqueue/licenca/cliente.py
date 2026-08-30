"""Conversa com o servidor de licenças. Só HTTP, nenhuma decisão.

A separação existe para o teste: quem decide se o app abre é `porta`, e
`porta` é testável trocando este cliente por um dublê. Se as duas
coisas morassem juntas, testar "o que acontece quando o servidor cai"
exigiria derrubar um servidor de verdade.

Duas falhas diferentes, duas exceções diferentes, e a diferença é a
coisa mais importante deste arquivo:

* `ErroDeRede` — não deu para falar com o servidor. Não prova nada
  sobre a licença. O app **não** pode apagar nada por causa disso; é
  exatamente o caso do sujeito jogando com a internet caindo.
* `ErroDoServidor` — o servidor respondeu e disse não. Aí sim há uma
  resposta para mostrar, e ela vem pronta em português.
"""

from __future__ import annotations

import requests

from . import embutido

#: Segundos de espera. Curto de propósito: isto pode rodar na abertura
#: do app, e ninguém aceita esperar meio minuto olhando para nada
#: porque um servidor de licença está lento.
ESPERA = 8.0


class ErroDeRede(Exception):
    """Servidor inalcançável, lento ou respondendo coisa sem sentido."""


class ErroDoServidor(Exception):
    """O servidor entendeu e recusou. A mensagem é para o usuário ler."""


def _url(caminho: str) -> str:
    base = embutido.servidor()
    if not base:
        raise ErroDeRede("nenhum servidor de licença configurado")
    return f"{base}{caminho}"


def _falar(caminho: str, corpo: dict) -> dict:
    try:
        resposta = requests.post(_url(caminho), json=corpo, timeout=ESPERA)
    except requests.RequestException as erro:
        raise ErroDeRede(str(erro)) from erro

    try:
        dados = resposta.json()
    except ValueError:
        dados = {}
    if not isinstance(dados, dict):
        dados = {}

    if resposta.status_code >= 500:
        # Erro do lado deles é problema de rede para os nossos fins: não
        # é uma recusa, é uma resposta que não vale nada.
        raise ErroDeRede(f"servidor com problema (HTTP {resposta.status_code})")
    if resposta.status_code >= 400:
        raise ErroDoServidor(
            str(dados.get("erro") or f"recusado pelo servidor (HTTP {resposta.status_code})")
        )
    return dados


def _bilhete_de(dados: dict) -> str:
    bilhete = str(dados.get("bilhete") or "").strip()
    if not bilhete:
        raise ErroDeRede("resposta sem licença")
    return bilhete


def ativar(chave: str, maquina: str, apelido: str = "", versao: str = "") -> str:
    """Troca a chave de ativação por um bilhete assinado."""
    return _bilhete_de(
        _falar(
            "/api/ativar",
            {
                "chave": chave.strip().upper(),
                "maquina": maquina,
                "apelido": apelido,
                "versao": versao,
            },
        )
    )


def validar(bilhete: str, maquina: str) -> str:
    """Renova o bilhete. É aqui que cancelamento e renovação aparecem."""
    return _bilhete_de(_falar("/api/validar", {"bilhete": bilhete, "maquina": maquina}))


def liberar(chave: str, maquina: str) -> dict:
    """Solta o slot desta máquina para a licença poder ir para outra."""
    return _falar("/api/liberar", {"chave": chave.strip().upper(), "maquina": maquina})


def saude() -> dict:
    try:
        resposta = requests.get(_url("/api/saude"), timeout=ESPERA)
        return resposta.json() if resposta.ok else {}
    except (requests.RequestException, ValueError) as erro:
        raise ErroDeRede(str(erro)) from erro
