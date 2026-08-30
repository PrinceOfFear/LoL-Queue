"""A decisão: este app pode abrir agora?

Regra que manda em todas as outras: **na dúvida, abre**. Um cliente
pagante impedido de jogar porque o servidor caiu, porque o Wi-Fi
oscilou ou porque o build saiu sem configuração é um estrago pior do
que uma cópia usada de graça. Por isso a trava só existe quando está
explicitamente configurada (`embutido.configurado()`), e por isso falha
de rede nunca apaga licença.

O que segura de verdade não é a checagem de abertura — é o prazo curto
do bilhete. Ele vale poucos dias e é renovado toda vez que o app fala
com o servidor. Cancelou o pagamento, parou de renovar, e em no máximo
`DIAS_OFFLINE` a licença morre sozinha, mesmo que a pessoa nunca mais
deixe o app ver a internet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import chave as formato
from . import cliente, embutido, estado, maquina
from .chave import Licenca, LicencaInvalida

#: Quanto tempo o app aguenta sem falar com o servidor. É o servidor
#: quem decide de fato (ele carimba o `expira`); isto aqui é só o valor
#: que o app espera e mostra na tela.
DIAS_OFFLINE = 7

#: De quanto em quanto tempo vale a pena renovar. Renovar em toda
#: abertura castigaria quem abre o app dez vezes por noite.
INTERVALO_RENOVACAO = 12 * 3600


@dataclass(frozen=True)
class Veredito:
    """Resposta da porta, pronta para virar tela.

    `precisa_ativar` é separado de `liberado` porque as duas telas são
    diferentes: "digite sua chave" (nunca ativou, ou a licença morreu)
    não é a mesma coisa que "não deu para conferir agora".
    """

    liberado: bool
    motivo: str = ""
    licenca: Licenca | None = None
    precisa_ativar: bool = False

    @property
    def dias_restantes(self) -> int:
        if self.licenca is None:
            return 0
        return max(0, int((self.licenca.assinatura_ate - time.time()) // 86400))


def ligada() -> bool:
    """A trava está configurada nesta build?"""
    return embutido.configurado()


def _conferir_local(est: estado.Estado, agora: float | None = None) -> Licenca:
    return formato.conferir(
        est.bilhete,
        embutido.chave_publica(),
        maquina=maquina.impressao(),
        agora=agora,
    )


def _guardar(est: estado.Estado) -> None:
    """Gravar não pode derrubar o app: disco cheio não é falta de licença."""
    try:
        est.save()
    except OSError:
        pass


def verificar(est: estado.Estado | None = None) -> Veredito:
    """Decisão de abertura. Não usa rede — tem que ser instantânea.

    A renovação online acontece depois, com a janela já aberta, em
    `renovar()`. Abertura de app não espera servidor.
    """
    if not ligada():
        return Veredito(True, "trava desligada nesta build")

    est = estado.Estado.load() if est is None else est
    relogio_ok = est.marcar_relogio()
    _guardar(est)

    if not est.bilhete:
        return Veredito(False, "ainda não ativado", precisa_ativar=True)

    try:
        licenca = _conferir_local(est)
    except LicencaInvalida as erro:
        return Veredito(False, str(erro), precisa_ativar=True)

    if not relogio_ok:
        # O relógio voltou no tempo. A validade offline deixou de valer
        # como prova; só o servidor pode dizer se ainda vale.
        try:
            licenca = _renovar_agora(est)
        except (cliente.ErroDeRede, cliente.ErroDoServidor, LicencaInvalida) as erro:
            return Veredito(
                False,
                f"o relógio do computador voltou no tempo e não deu para "
                f"confirmar a licença ({erro}). Acerte a data e hora do "
                f"Windows e abra de novo.",
                precisa_ativar=False,
            )

    return Veredito(True, "licença válida", licenca=licenca)


def _renovar_agora(est: estado.Estado) -> Licenca:
    """Fala com o servidor e guarda o bilhete novo. Levanta se der ruim."""
    novo = cliente.validar(est.bilhete, maquina.impressao())
    licenca = formato.conferir(
        novo, embutido.chave_publica(), maquina=maquina.impressao()
    )
    est.bilhete = novo
    est.chave = licenca.chave or est.chave
    est.validado_em = time.time()
    est.mensagem = ""
    _guardar(est)
    return licenca


def renovar(forcar: bool = False) -> Veredito:
    """Renovação de fundo. Chamar com a janela já aberta, fora da thread da UI.

    Silenciosa por natureza: o caso comum é "sem internet agora", e isso
    não é assunto do usuário enquanto o bilhete ainda vale.
    """
    if not ligada():
        return Veredito(True, "trava desligada nesta build")

    est = estado.Estado.load()
    if not est.bilhete:
        return Veredito(False, "ainda não ativado", precisa_ativar=True)
    if not forcar and time.time() - est.validado_em < INTERVALO_RENOVACAO:
        try:
            return Veredito(True, "renovado recentemente", licenca=_conferir_local(est))
        except LicencaInvalida:
            pass  # bilhete velho apesar da data: renova de verdade

    try:
        return Veredito(True, "licença renovada", licenca=_renovar_agora(est))
    except cliente.ErroDeRede as erro:
        # Sem internet. O bilhete atual continua valendo até vencer.
        est.mensagem = str(erro)
        _guardar(est)
        try:
            return Veredito(True, "sem internet, usando a licença guardada",
                            licenca=_conferir_local(est))
        except LicencaInvalida as fim:
            return Veredito(False, str(fim), precisa_ativar=True)
    except (cliente.ErroDoServidor, LicencaInvalida) as erro:
        # O servidor recusou: cancelada, revogada ou trocada de máquina.
        est.limpar()
        est.mensagem = str(erro)
        _guardar(est)
        return Veredito(False, str(erro), precisa_ativar=True)


def ativar(chave_digitada: str, versao: str = "") -> Veredito:
    """Troca a chave que a pessoa digitou por uma licença guardada."""
    digitada = (chave_digitada or "").strip().upper()
    if not digitada:
        return Veredito(False, "digite a chave que veio na compra", precisa_ativar=True)
    if not ligada():
        return Veredito(True, "trava desligada nesta build")

    try:
        bilhete = cliente.ativar(
            digitada, maquina.impressao(), maquina.apelido(), versao
        )
        licenca = formato.conferir(
            bilhete, embutido.chave_publica(), maquina=maquina.impressao()
        )
    except cliente.ErroDeRede as erro:
        return Veredito(
            False,
            f"não deu para falar com o servidor agora ({erro}). "
            "Confira sua internet e tente de novo.",
            precisa_ativar=True,
        )
    except (cliente.ErroDoServidor, LicencaInvalida) as erro:
        return Veredito(False, str(erro), precisa_ativar=True)

    est = estado.Estado.load()
    est.bilhete = bilhete
    est.chave = licenca.chave or digitada
    est.validado_em = time.time()
    est.mensagem = ""
    est.marcar_relogio()
    _guardar(est)
    return Veredito(True, "licença ativada", licenca=licenca)


def liberar_este_computador() -> Veredito:
    """Solta o slot para usar a licença em outro PC.

    Existe porque a alternativa é o cliente formatar o PC, perder o
    slot e abrir um chamado. Com botão, ele se resolve sozinho.
    """
    if not ligada():
        return Veredito(True, "trava desligada nesta build")
    est = estado.Estado.load()
    if not est.chave:
        return Veredito(False, "não há licença ativada neste computador")
    try:
        cliente.liberar(est.chave, maquina.impressao())
    except cliente.ErroDeRede as erro:
        return Veredito(False, f"sem conexão com o servidor ({erro})")
    except cliente.ErroDoServidor as erro:
        return Veredito(False, str(erro))
    est.limpar()
    _guardar(est)
    return Veredito(False, "licença liberada deste computador", precisa_ativar=True)


def resumo() -> str:
    """Uma linha para mostrar nas configurações."""
    if not ligada():
        return "Licença: não exigida nesta versão."
    veredito = verificar()
    if not veredito.liberado:
        return f"Licença: {veredito.motivo}."
    licenca = veredito.licenca
    if licenca is None:
        return "Licença: liberada."
    quando = time.strftime("%d/%m/%Y", time.localtime(licenca.assinatura_ate))
    return f"Licença {licenca.plano or 'ativa'} — válida até {quando}."
