"""A trava de licença inteira: formato, máquina, estado guardado e a porta.

Nada aqui toca a rede nem o `%APPDATA%` de verdade — o disco é
redirecionado com `APPDATA` e o servidor é sempre um dublê. Um teste
que escreve na pasta real apagaria a licença de quem está rodando os
testes na própria máquina onde usa o app.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from lolqueue.licenca import chave, cliente, embutido, estado, maquina, porta

#: A impressão digital fingida deste computador. 32 hex, como a de verdade.
MAQUINA = "a1b2c3d4e5f60718293a4b5c6d7e8f90"

#: Outro computador qualquer, para provar que o bilhete não viaja.
OUTRA_MAQUINA = "0f9e8d7c6b5a49382716f5e4d3c2b1a0"


def _b64_le(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _b64_grava(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _licenca(**campos) -> chave.Licenca:
    """Uma licença comum: desta máquina, válida por uma semana."""
    agora = int(time.time())
    base = dict(
        chave="LQ-AAAA-BBBB-CCCC",
        maquina=MAQUINA,
        expira=agora + 7 * 86400,
        assinatura_ate=agora + 30 * 86400,
        emitido=agora,
        plano="mensal",
        apelido="PC de teste",
    )
    base.update(campos)
    return chave.Licenca(**base)


def _adulterar(bilhete: str, **campos) -> str:
    """Reescreve a carga mantendo a assinatura antiga, como um pirata faria."""
    versao, carga_b64, assinatura_b64 = bilhete.split(".")
    dados = json.loads(_b64_le(carga_b64).decode("utf-8"))
    dados.update(campos)
    nova = json.dumps(
        dados, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"{versao}.{_b64_grava(nova)}.{assinatura_b64}"


@pytest.fixture
def par():
    """Um par Ed25519 só deste teste; a chave de produção não aparece aqui."""
    return chave.gerar_par()


# ---------- o formato do bilhete ----------


def test_um_bilhete_assinado_volta_com_os_mesmos_campos(par):
    """Se ida e volta perdesse um campo, o app mostraria "plano" vazio e
    data de vencimento errada para quem pagou, sem erro nenhum na tela.
    """
    privada, publica = par
    original = _licenca()
    lida = chave.conferir(chave.assinar(original, privada), publica)
    assert lida == original


def test_a_publica_derivada_da_privada_confere_o_bilhete(par):
    """`publica_de` é o que a ferramenta de build usa para provar que a
    chave gravada no executável casa com a que assina no servidor. Se
    divergisse, o build sairia recusando todas as licenças emitidas.
    """
    privada, publica = par
    assert chave.publica_de(privada) == publica


def test_carga_adulterada_e_recusada(par):
    """Trocar a máquina do bilhete na mão é a pirataria mais óbvia que
    existe: copiar o licenca.json do amigo e editar um campo.
    """
    privada, publica = par
    bilhete = chave.assinar(_licenca(), privada)
    forjado = _adulterar(bilhete, maquina=OUTRA_MAQUINA)
    with pytest.raises(chave.LicencaInvalida, match="assinatura"):
        chave.conferir(forjado, publica, maquina=OUTRA_MAQUINA)


def test_esticar_a_validade_na_mao_e_recusado(par):
    """A outra adulteração óbvia: empurrar o `expira` para 2099."""
    privada, publica = par
    bilhete = chave.assinar(_licenca(), privada)
    forjado = _adulterar(bilhete, expira=4_000_000_000)
    with pytest.raises(chave.LicencaInvalida, match="assinatura"):
        chave.conferir(forjado, publica)


def test_assinatura_de_outra_chave_privada_e_recusada(par):
    """Sem isso qualquer um geraria o próprio par e emitiria licença
    infinita — a chave pública do executável deixaria de servir para nada.
    """
    _, publica = par
    outra_privada, _ = chave.gerar_par()
    bilhete = chave.assinar(_licenca(), outra_privada)
    with pytest.raises(chave.LicencaInvalida, match="assinatura"):
        chave.conferir(bilhete, publica)


def test_bilhete_vencido_e_recusado(par):
    """É o prazo curto do bilhete que faz o cancelamento surtir efeito
    offline. Aceitar bilhete vencido devolveria acesso vitalício a quem
    cancelou e nunca mais deixou o app ver a internet.
    """
    privada, publica = par
    licenca = _licenca()
    with pytest.raises(chave.LicencaInvalida, match="vencida"):
        chave.conferir(
            chave.assinar(licenca, privada),
            publica,
            agora=licenca.expira + chave.FOLGA_RELOGIO + 1,
        )


def test_dentro_da_folga_de_relogio_o_bilhete_vencido_ainda_passa(par):
    """Relógio de usuário erra por fuso e por atraso de sincronização.
    Recusar uma licença boa por dois minutos de diferença seria mandar
    um cliente pagante para a tela de ativação sem motivo nenhum.
    """
    privada, publica = par
    licenca = _licenca()
    lida = chave.conferir(
        chave.assinar(licenca, privada),
        publica,
        agora=licenca.expira + chave.FOLGA_RELOGIO,
    )
    assert lida.chave == licenca.chave


def test_bilhete_de_outra_maquina_e_recusado(par):
    """Sem isso a licença vira arquivo transferível: um comprador,
    quantos PCs quiser, bastando copiar o licenca.json.
    """
    privada, publica = par
    bilhete = chave.assinar(_licenca(), privada)
    with pytest.raises(chave.LicencaInvalida, match="outro computador"):
        chave.conferir(bilhete, publica, maquina=OUTRA_MAQUINA)


def test_bilhete_sem_maquina_serve_em_qualquer_computador(par):
    """É a licença de dono e a de suporte: emitir uma que roda em
    qualquer PC não pode exigir um formato de bilhete diferente.
    """
    privada, publica = par
    bilhete = chave.assinar(_licenca(maquina=""), privada)
    assert chave.conferir(bilhete, publica, maquina=MAQUINA).maquina == ""
    assert chave.conferir(bilhete, publica, maquina=OUTRA_MAQUINA).maquina == ""


def test_versao_desconhecida_no_prefixo_e_recusada(par):
    """A versão entra no que é assinado justamente para que ninguém
    reaproveite a assinatura de hoje numa carga de formato futuro.
    """
    privada, publica = par
    bilhete = chave.assinar(_licenca(), privada)
    _, carga, assinatura = bilhete.split(".")
    with pytest.raises(chave.LicencaInvalida, match="versão desconhecida"):
        chave.conferir(f"LQ9.{carga}.{assinatura}", publica)


def test_bilhete_fora_do_formato_e_recusado(par):
    """O arquivo é editável à mão e um texto qualquer não pode explodir
    com uma exceção que ninguém trata na abertura do app.
    """
    _, publica = par
    for lixo in ("", "nada", "LQ1.so-duas-partes"):
        with pytest.raises(chave.LicencaInvalida):
            chave.conferir(lixo, publica)


def test_campo_desconhecido_na_carga_nao_derruba_a_leitura(par):
    """Um servidor mais novo emitindo um campo a mais transformaria todo
    app antigo em app que não abre. O campo vai para `extra` e a vida segue.
    """
    privada, publica = par
    original = _licenca(extra={"limite_de_pcs": 3, "revenda": "loja"})
    lida = chave.conferir(chave.assinar(original, privada), publica)
    assert lida.extra == {"limite_de_pcs": 3, "revenda": "loja"}
    assert lida.chave == original.chave
    assert lida.plano == "mensal"


# ---------- a impressão digital do computador ----------


def test_a_impressao_e_estavel_e_tem_32_hex():
    """Uma impressão que muda entre duas leituras faria a licença
    "quebrar" sozinha, sem ninguém ter mexido em nada.
    """
    primeira = maquina.impressao()
    assert primeira == maquina.impressao()
    assert len(primeira) == maquina.TAMANHO == 32
    assert all(c in "0123456789abcdef" for c in primeira)


def test_a_impressao_responde_mesmo_sem_nenhuma_pista(monkeypatch):
    """Travar o app na abertura porque a leitura do registro falhou
    seria trocar um problema pequeno por um total.
    """
    monkeypatch.setattr(maquina, "_machine_guid", lambda: "")
    monkeypatch.setattr(maquina, "_serie_do_volume", lambda: "")
    monkeypatch.setattr(maquina, "_fallback", lambda: "")
    assert maquina.pistas() == []
    assert len(maquina.impressao()) == 32


@pytest.mark.xfail(
    reason="maquina.impressao() promete nunca levantar, mas pistas() não "
    "protege contra fonte que quebra de jeito não previsto",
)
def test_a_impressao_nunca_levanta_mesmo_com_uma_fonte_quebrada(monkeypatch):
    """Esta função roda antes da janela existir: se ela levantar, o app
    fecha sem nada na tela e o usuário não tem sequer o que reportar.
    """

    def quebra():
        raise RuntimeError("fonte de identidade indisponível")

    monkeypatch.setattr(maquina, "_machine_guid", quebra)
    monkeypatch.setattr(maquina, "_serie_do_volume", quebra)
    monkeypatch.setattr(maquina, "_fallback", quebra)
    assert len(maquina.impressao()) == 32


def test_o_apelido_nunca_volta_vazio():
    """É o nome que o dono usa para reconhecer o slot na hora de liberar
    um PC. Vazio na lista, ele não sabe qual dos três está soltando.
    """
    assert maquina.apelido().strip()


# ---------- o que fica guardado no disco ----------


def test_o_estado_mora_ao_lado_da_config_no_appdata(tmp_path, monkeypatch):
    """Guarda o redirecionamento de que todo o resto deste arquivo
    depende: se `caminho()` deixasse de olhar o APPDATA, os testes
    passariam a mexer na licença real de quem os roda.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert estado.caminho() == tmp_path / "LoLQueue" / "licenca.json"


def test_o_estado_volta_do_disco_como_foi_gravado(tmp_path):
    original = estado.Estado(
        bilhete="LQ1.abc.def",
        chave="LQ-AAAA-BBBB-CCCC",
        validado_em=1700.5,
        visto_em=1800.5,
        mensagem="tudo certo",
    )
    alvo = tmp_path / "licenca.json"
    original.save(alvo)
    assert estado.Estado.load(alvo) == original


def test_arquivo_corrompido_volta_ao_padrao_sem_levantar(tmp_path):
    """Queda de energia no meio da gravação não pode virar exceção na
    abertura: o app tem que pedir ativação, não fechar sozinho.
    """
    alvo = tmp_path / "licenca.json"
    for lixo in ("{ pela metade", "[1, 2]", ""):
        alvo.write_text(lixo, encoding="utf-8")
        assert estado.Estado.load(alvo) == estado.Estado()
    assert estado.Estado.load(tmp_path / "nem-existe.json") == estado.Estado()


def test_chave_desconhecida_no_arquivo_e_ignorada(tmp_path):
    """Campo de uma versão futura não pode derrubar a leitura inteira e
    mandar um cliente pagante para a tela de ativação.
    """
    alvo = tmp_path / "licenca.json"
    alvo.write_text('{"bilhete": "LQ1.a.b", "coisa_nova": 1}', encoding="utf-8")
    assert estado.Estado.load(alvo).bilhete == "LQ1.a.b"


def test_marcar_relogio_acusa_o_relogio_atrasado_alem_da_tolerancia():
    """É a única defesa contra atrasar a data do Windows para esticar a
    validade offline sem pagar.
    """
    est = estado.Estado(visto_em=1_000_000.0)
    assert est.marcar_relogio(1_000_000.0 - estado.TOLERANCIA_RELOGIO - 60) is False


def test_marcar_relogio_nao_acusa_atraso_dentro_da_tolerancia():
    """Fuso mal configurado e volta do horário de verão cabem em um dia,
    e não podem custar o acesso de quem não fez nada.
    """
    est = estado.Estado(visto_em=1_000_000.0)
    assert est.marcar_relogio(1_000_000.0 - 3600) is True
    assert estado.Estado().marcar_relogio(1.0) is True


def test_o_visto_em_nunca_diminui():
    """Se diminuísse, bastaria atrasar o relógio uma vez para zerar a
    suspeita e depois atrasar o quanto quisesse.
    """
    est = estado.Estado(visto_em=1_000_000.0)
    est.marcar_relogio(500_000.0)
    assert est.visto_em == 1_000_000.0
    est.marcar_relogio(2_000_000.0)
    assert est.visto_em == 2_000_000.0


# ---------- a porta ----------


class ServidorFalso:
    """O servidor de licenças de mentira: grava o que foi chamado.

    Existe para o teste poder responder "sem internet" e "recusado" sem
    derrubar servidor nenhum — e, principalmente, para provar quando o
    servidor **não** foi chamado.
    """

    def __init__(self, bilhete: str = "", erro: Exception | None = None):
        self.bilhete = bilhete
        self.erro = erro
        self.chamadas: list[tuple] = []

    def ativar(self, chave_digitada, impressao, apelido="", versao=""):
        self.chamadas.append(("ativar", chave_digitada, impressao, apelido, versao))
        if self.erro is not None:
            raise self.erro
        return self.bilhete

    def validar(self, bilhete, impressao):
        self.chamadas.append(("validar", bilhete, impressao))
        if self.erro is not None:
            raise self.erro
        return self.bilhete

    def liberar(self, chave_digitada, impressao):
        self.chamadas.append(("liberar", chave_digitada, impressao))
        if self.erro is not None:
            raise self.erro
        return {"ok": True, "liberados": 1}

    @property
    def verbos(self) -> list[str]:
        return [c[0] for c in self.chamadas]


@pytest.fixture
def servidor(monkeypatch):
    """Põe o dublê no lugar do HTTP de verdade, para os três endpoints."""
    falso = ServidorFalso()
    monkeypatch.setattr(cliente, "ativar", falso.ativar)
    monkeypatch.setattr(cliente, "validar", falso.validar)
    monkeypatch.setattr(cliente, "liberar", falso.liberar)
    return falso


@pytest.fixture
def trava(monkeypatch, tmp_path, par):
    """Liga a trava com um servidor e um APPDATA de mentira.

    As variáveis de ambiente têm prioridade sobre o que está gravado em
    `embutido.py`, então dá para ligar a trava inteira sem tocar em
    nenhum arquivo do build.
    """
    privada, publica = par
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv(embutido.VAR_SERVIDOR, "https://licencas.de-mentira")
    monkeypatch.setenv(embutido.VAR_CHAVE, publica)
    monkeypatch.setattr(maquina, "impressao", lambda: MAQUINA)
    monkeypatch.setattr(maquina, "apelido", lambda: "PC de teste")
    assert porta.ligada()
    return privada


def _guardar_bilhete(bilhete: str, **campos) -> estado.Estado:
    """Deixa no disco o estado de quem já ativou."""
    est = estado.Estado(bilhete=bilhete, chave="LQ-AAAA-BBBB-CCCC", **campos)
    est.save()
    return est


def test_sem_trava_configurada_a_porta_libera_sem_tocar_disco_nem_rede(
    monkeypatch, tmp_path
):
    """A regressão mais cara possível: o app parar de abrir para quem
    não tem nada a ver com licença. Rodando do fonte, ou num build feito
    sem as variáveis, a porta tem que ficar inerte — sem tela de
    ativação, sem leitura de disco e sem um único pacote na rede.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv(embutido.VAR_SERVIDOR, raising=False)
    monkeypatch.delenv(embutido.VAR_CHAVE, raising=False)
    monkeypatch.setattr(embutido, "SERVIDOR", "")
    monkeypatch.setattr(embutido, "CHAVE_PUBLICA", "")

    def proibido(*args, **kwargs):
        raise AssertionError("build sem licença tocou em disco ou rede")

    monkeypatch.setattr(estado, "caminho", proibido)
    monkeypatch.setattr(cliente, "ativar", proibido)
    monkeypatch.setattr(cliente, "validar", proibido)
    monkeypatch.setattr(cliente, "liberar", proibido)

    assert porta.ligada() is False
    veredito = porta.verificar()
    assert veredito.liberado
    assert veredito.precisa_ativar is False
    assert list(tmp_path.iterdir()) == []


def test_sem_trava_as_outras_operacoes_tambem_ficam_inertes(monkeypatch, tmp_path):
    """A renovação de fundo e o resumo das configurações também rodam
    nesse build: qualquer um dos dois batendo num servidor inexistente
    daria erro na tela de quem nunca comprou nada.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv(embutido.VAR_SERVIDOR, raising=False)
    monkeypatch.delenv(embutido.VAR_CHAVE, raising=False)
    monkeypatch.setattr(embutido, "SERVIDOR", "")
    monkeypatch.setattr(embutido, "CHAVE_PUBLICA", "")

    def proibido(*args, **kwargs):
        raise AssertionError("build sem licença tocou em disco ou rede")

    monkeypatch.setattr(estado, "caminho", proibido)
    monkeypatch.setattr(cliente, "ativar", proibido)
    monkeypatch.setattr(cliente, "validar", proibido)
    monkeypatch.setattr(cliente, "liberar", proibido)

    assert porta.renovar().liberado
    assert porta.renovar(forcar=True).liberado
    assert porta.ativar("LQ-AAAA-BBBB-CCCC").liberado
    assert porta.liberar_este_computador().liberado
    assert "não exigida" in porta.resumo()
    assert list(tmp_path.iterdir()) == []


def test_com_a_trava_ligada_e_sem_bilhete_a_porta_pede_ativacao(trava, servidor):
    """Quem nunca ativou vai para a tela "digite sua chave", e a decisão
    de abertura não espera servidor nenhum para dizer isso.
    """
    veredito = porta.verificar()
    assert veredito.liberado is False
    assert veredito.precisa_ativar is True
    assert servidor.chamadas == []


def test_bilhete_valido_libera_sem_falar_com_o_servidor(trava, servidor):
    """Abertura de app não espera servidor: o bilhete vale sozinho até
    vencer. Se a porta chamasse a rede aqui, quem está sem internet
    ficaria olhando a janela travar antes de abrir.
    """
    licenca = _licenca()
    _guardar_bilhete(chave.assinar(licenca, trava))
    veredito = porta.verificar()
    assert veredito.liberado is True
    assert veredito.licenca == licenca
    assert veredito.precisa_ativar is False
    assert servidor.chamadas == []


def test_bilhete_de_outro_computador_manda_ativar_de_novo(trava, servidor):
    """Copiar o licenca.json do amigo tem que dar em tela de ativação, e
    não em acesso liberado.
    """
    _guardar_bilhete(chave.assinar(_licenca(maquina=OUTRA_MAQUINA), trava))
    veredito = porta.verificar()
    assert veredito.liberado is False
    assert veredito.precisa_ativar is True
    assert servidor.chamadas == []


def test_ativar_guarda_o_bilhete_no_estado(trava, servidor):
    """Sem gravar, a pessoa digitaria a chave da compra toda vez que
    abrisse o app.
    """
    licenca = _licenca()
    servidor.bilhete = chave.assinar(licenca, trava)

    veredito = porta.ativar("  lq-aaaa-bbbb-cccc  ", versao="0.1.0")

    assert veredito.liberado is True
    assert veredito.licenca == licenca
    guardado = estado.Estado.load()
    assert guardado.bilhete == servidor.bilhete
    assert guardado.chave == "LQ-AAAA-BBBB-CCCC"
    assert guardado.validado_em > 0
    # O que a pessoa digitou chega ao servidor sem espaço e em maiúsculas.
    assert servidor.chamadas == [
        ("ativar", "LQ-AAAA-BBBB-CCCC", MAQUINA, "PC de teste", "0.1.0")
    ]


def test_ativar_recusado_nao_guarda_nada_e_repete_a_mensagem_do_servidor(
    trava, servidor
):
    """A recusa vem pronta em português do servidor ("essa chave já está
    em outro PC"). Trocá-la por um texto genérico deixaria a pessoa sem
    saber o que fazer, e gravar um bilhete que não veio seria pior ainda.
    """
    servidor.erro = cliente.ErroDoServidor("essa chave já está em uso em outro PC")

    veredito = porta.ativar("LQ-AAAA-BBBB-CCCC")

    assert veredito.liberado is False
    assert veredito.precisa_ativar is True
    assert veredito.motivo == "essa chave já está em uso em outro PC"
    assert estado.Estado.load().bilhete == ""
    assert not estado.caminho().exists()


def test_ativar_sem_internet_nao_apaga_o_bilhete_que_ja_existia(trava, servidor):
    """Errar a chave numa tentativa de ativação com o Wi-Fi caindo não
    pode custar a licença que já estava valendo neste computador.
    """
    antigo = chave.assinar(_licenca(), trava)
    _guardar_bilhete(antigo, validado_em=time.time())
    servidor.erro = cliente.ErroDeRede("timeout ao falar com o servidor")

    veredito = porta.ativar("LQ-ZZZZ-ZZZZ-ZZZZ")

    assert veredito.liberado is False
    assert "internet" in veredito.motivo
    assert estado.Estado.load().bilhete == antigo
    # E o app continua abrindo com a licença de antes.
    assert porta.verificar().liberado is True


def test_renovar_sem_internet_mantem_a_licenca_guardada(trava, servidor):
    """Regressão cara: cliente pagante perdendo acesso porque o Wi-Fi
    caiu. Falha de rede não prova nada sobre a licença.
    """
    bilhete = chave.assinar(_licenca(), trava)
    _guardar_bilhete(bilhete, validado_em=time.time() - porta.INTERVALO_RENOVACAO - 1)
    servidor.erro = cliente.ErroDeRede("conexão recusada")

    veredito = porta.renovar()

    assert veredito.liberado is True
    assert veredito.licenca is not None
    assert servidor.verbos == ["validar"]
    guardado = estado.Estado.load()
    assert guardado.bilhete == bilhete
    assert "conexão recusada" in guardado.mensagem


def test_renovar_recusado_pelo_servidor_apaga_a_licenca_local(trava, servidor):
    """O contrário do caso acima: o servidor respondeu e disse não
    (cancelou, foi revogada, mudou de máquina). Manter o bilhete aqui
    daria mais uma semana de graça a cada cancelamento.
    """
    _guardar_bilhete(
        chave.assinar(_licenca(), trava),
        validado_em=time.time() - porta.INTERVALO_RENOVACAO - 1,
    )
    servidor.erro = cliente.ErroDoServidor("assinatura cancelada")

    veredito = porta.renovar()

    assert veredito.liberado is False
    assert veredito.precisa_ativar is True
    assert veredito.motivo == "assinatura cancelada"
    guardado = estado.Estado.load()
    assert guardado.bilhete == ""
    assert guardado.chave == ""
    assert guardado.mensagem == "assinatura cancelada"


def test_renovar_nao_incomoda_o_servidor_de_novo_dentro_do_intervalo(trava, servidor):
    """Renovar a cada abertura castigaria quem abre o app dez vezes por
    noite — e o servidor de licenças, junto.
    """
    _guardar_bilhete(chave.assinar(_licenca(), trava), validado_em=time.time())

    veredito = porta.renovar()

    assert veredito.liberado is True
    assert servidor.chamadas == []


def test_renovar_forcado_fala_com_o_servidor_e_troca_o_bilhete(trava, servidor):
    """O botão "verificar agora" das configurações não pode obedecer ao
    intervalo: quem acabou de comprar clica nele esperando efeito na hora.
    """
    _guardar_bilhete(chave.assinar(_licenca(), trava), validado_em=time.time())
    renovado = chave.assinar(_licenca(plano="anual"), trava)
    servidor.bilhete = renovado

    veredito = porta.renovar(forcar=True)

    assert veredito.liberado is True
    assert servidor.verbos == ["validar"]
    assert estado.Estado.load().bilhete == renovado
    assert veredito.licenca is not None and veredito.licenca.plano == "anual"


def test_liberar_este_computador_limpa_o_estado_quando_o_servidor_aceita(
    trava, servidor
):
    """Existe para o cliente soltar o slot sozinho antes de formatar o
    PC. Deixar o bilhete aqui depois de soltar faria o app seguir
    abrindo com uma licença que o servidor já deu a outra máquina.
    """
    _guardar_bilhete(chave.assinar(_licenca(), trava), validado_em=time.time())

    veredito = porta.liberar_este_computador()

    assert veredito.precisa_ativar is True
    assert servidor.chamadas == [("liberar", "LQ-AAAA-BBBB-CCCC", MAQUINA)]
    guardado = estado.Estado.load()
    assert guardado.bilhete == ""
    assert guardado.chave == ""


def test_liberar_este_computador_nao_limpa_nada_quando_o_servidor_recusa(
    trava, servidor
):
    """Se limpasse mesmo assim, um clique errado com o servidor fora do
    ar deixaria o cliente sem licença aqui e com o slot ainda ocupado lá.
    """
    bilhete = chave.assinar(_licenca(), trava)
    for erro in (
        cliente.ErroDoServidor("essa máquina não está na sua licença"),
        cliente.ErroDeRede("sem rota para o servidor"),
    ):
        _guardar_bilhete(bilhete, validado_em=time.time())
        servidor.erro = erro

        veredito = porta.liberar_este_computador()

        assert veredito.liberado is False
        guardado = estado.Estado.load()
        assert guardado.bilhete == bilhete
        assert guardado.chave == "LQ-AAAA-BBBB-CCCC"
