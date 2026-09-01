# Relatorio de seguranca — LoL Queue

Data da verificacao: 2026-09-01  
Escopo: `lolqueue/`, `servidor/`, `tools/` e `main.py` (codigo Python), com foco no licenciamento mensal e na integracao PicPay.

## Resumo executivo

As verificacoes locais passaram sem achados criticos ou altos no codigo auditado. A suite terminou com **1040 testes aprovados e 1 xfail**; a compilacao Python passou. O build de venda agora falha fechado quando a URL e a chave publica de licenca nao estao embutidas.

O plugin `codex-security@openai-curated` esta instalado e habilitado. Tentativas nesta sessao e em uma execucao headless isolada confirmaram que os comandos MCP de scan nao foram expostos pelo runtime; portanto este documento nao afirma que uma varredura profunda do plugin foi executada. Ela deve ser rodada depois que o servidor MCP for carregado em uma nova sessao.

## Controles corrigidos

### SBP-001 — Build sem licenca embutida

- **Severidade:** alta antes da correcao; resolvida no checkout atual.
- **Local:** `tools/build.ps1:106-114`.
- **Evidencia:** o script consulta `embutido.configurado()` e interrompe o build se a licenca estiver desligada; somente `-AllowUnlicensed` permite um teste local e emite aviso para nao distribuir.
- **Impacto anterior:** um pacote criado sem `preparar_build.py` poderia abrir para qualquer pessoa.
- **Correcao:** a entrega comercial exige servidor HTTPS e chave publica Ed25519. A flag de excecao e explicita e nao e usada na publicacao.
- **Validacao:** `powershell -ExecutionPolicy Bypass -File tools\build.ps1` foi recusado com a mensagem de licenca desligada.

### SBP-002 — Licenca mensal e vinculo ao computador

- **Severidade:** alta; implementada e coberta por testes.
- **Local:** `servidor/app.py:167-173, 307-370`, `servidor/config.py:56-85` e `servidor/picpay.py:70-105`.
- **Evidencia:** em producao a API desliga a documentacao, valida `Host`, exige `LICENSE_PRIVATE_KEY` e `PICPAY_WEBHOOK_TOKEN`, usa HTTPS para o PicPay, nao herda proxies e exige o token de webhook com comparacao em tempo constante.
- **Impacto:** a ativacao so funciona para chave cadastrada, assinatura ativa e mesma impressao de computador. O webhook confere valor, evento e idempotencia antes de estender um mes; cancelamento/estorno revoga.
- **Correcao:** servidor separado, SQLite transacional, bilhetes Ed25519 curtos e `temporaryCardToken`; nenhum numero de cartao/CVV entra no app.
- **Validacao:** `tests/test_license_server.py` cobre assinatura, maquina, webhook, replay, valor e fluxo de assinatura.

### SBP-003 — Checkout externo e webhook atomico

- **Severidade:** alta; implementada e coberta por testes.
- **Local:** `servidor/checkout.py`, `servidor/app.py` e `servidor/db.py`.
- **Evidencia:** o checkout tokeniza o cartao no SDK oficial, usa CSP com nonce,
  CORS por origem exata e envia somente `temporaryCardToken`. O registro do
  evento e a atualizacao da licenca usam uma transacao unica.
- **Validacao:** Playwright carregou a pagina e concluiu o fluxo mockado sem
  erros de console; 13 testes focados do servidor passaram.

## Risco residual e operacao

1. `tools/emitir_licenca.py` ainda existe como emergencia do operador. A validade manual padrao e 30 dias (`DIAS_PADRAO`); licencas longas exigem `LOLQUEUE_ALLOW_LONG_LICENSE=1` e uma licenca sem computador exige tambem `LOLQUEUE_ALLOW_UNBOUND_LICENSE=1`, limitada a 7 dias. Essas variaveis nao devem existir no host de producao.
2. O banco e a chave privada devem ficar fora do repositorio e sob backup criptografado. O webhook PicPay precisa de URL HTTPS publica, sem query string, conforme a configuracao do Painel Lojista.
3. O Bandit (limite medio/alto) e o pip-audit da arvore do projeto passaram sem achados. O workflow `.github/workflows/security.yml` instala `.[security]`, atualiza o pip e executa ambos antes de aceitar uma alteracao.
4. O cliente nao consegue impedir um administrador do proprio computador de modificar o executavel Python. A protecao real contra copia e a assinatura do servidor, o vinculo de maquina, o build licenciado e a assinatura de integridade da distribuicao; nenhum mecanismo local promete inviolabilidade.

## Comandos reproduziveis

```text
py -3.14 tools/auditar_seguranca.py --tests --release
py -3.14 -m pytest tests -q
py -3.14 -m compileall -q lolqueue servidor tools main.py
py -3.14 -m bandit -q -r lolqueue servidor tools -ll
py -3.14 -m pip_audit --progress-spinner off --skip-editable .
```
