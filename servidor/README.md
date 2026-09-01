# Servidor de licencas do LoL Queue

Este servico e a parte que deve ficar em um host HTTPS (por exemplo, um
servidor pequeno ou uma plataforma de deploy). O executavel do jogador recebe
somente a URL e a chave **publica** Ed25519. A chave privada e os segredos do
PicPay ficam apenas nas variaveis de ambiente do host.

## Fluxo mensal

1. Crie no Painel/API do PicPay um plano de recorrencia de `R$ 20,00` por mes
   (o valor e `2000` centavos e pode ser alterado antes do primeiro cliente).
2. Cadastre no PicPay uma URL HTTPS sem query string para
   `/webhooks/picpay` e guarde o token `Authorization` em
   `PICPAY_WEBHOOK_TOKEN`.
3. Gere o par Ed25519 com `py -3 tools/gerar_chaves.py`. A privada vai para
   `LICENSE_PRIVATE_KEY`; a publica e usada em `tools/preparar_build.py`.
4. Provisione cada chave de ativacao no banco com validade inicial e o
   `picpay_subscription_id` devolvido pelo PicPay.
5. O webhook so estende a validade quando o evento autenticado tem o valor
   exato do plano. Eventos repetidos sao idempotentes; cancelamentos e
   estornos revogam a licenca.

O endpoint `POST /api/assinaturas` recebe somente os dados cadastrais e o
`temporaryCardToken` emitido pelo SDK do PicPay. Ele devolve uma chave que fica
inutilizavel ate o primeiro webhook `PAID`/`AUTHORIZED`; assim, criar uma
assinatura pendente nunca libera o aplicativo de graca.

O endpoint `GET /checkout` serve uma pagina web externa ao executavel. Ela usa
o SDK oficial do PicPay para gerar o `temporaryCardToken` no navegador e envia
ao backend apenas esse token. Configure `PICPAY_MERCHANT_CREDENTIAL`,
`PICPAY_TRANSPARENT_TOKEN` e, se a pagina ficar em outro dominio,
`CHECKOUT_API_BASE_URL` e `CHECKOUT_ALLOWED_ORIGINS`. Nunca envie numero, CVV
ou segredo para o LoL Queue. A lista de origens e exata (sem wildcard) para
que a pagina externa possa chamar somente esta API.

## Configuracao minima

```text
LICENSE_ENV=production
LICENSE_DATABASE=/var/lib/lolqueue/licencas.db
LICENSE_PRIVATE_KEY=<base64url da chave privada>
LICENSE_PRICE_CENTS=2000
LICENSE_CURRENCY=BRL
LICENSE_GRACE_DAYS=3
LICENSE_OFFLINE_DAYS=7
LICENSE_ALLOWED_HOSTS=licencas.seudominio.com
PICPAY_CLIENT_ID=<segredo do host>
PICPAY_CLIENT_SECRET=<segredo do host>
PICPAY_PLAN_ID=<id do plano mensal>
PICPAY_MERCHANT_CREDENTIAL=<CNPJ da loja para o SDK>
PICPAY_TRANSPARENT_TOKEN=<token transparente fornecido pelo PicPay>
PICPAY_SDK_URL=https://checkout.picpay.com/cdn/pp-transparent-v1.0.0.js
CHECKOUT_API_BASE_URL=https://licencas.seudominio.com
CHECKOUT_ALLOWED_ORIGINS=https://pagamento.seudominio.com
PICPAY_WEBHOOK_TOKEN=<token gerado no Painel Lojista>
```

Em producao a API desliga `/docs`, valida o `Host`, exige HTTPS para chamadas
ao PicPay, desabilita proxy herdado do ambiente e limita o corpo do webhook.

## Execucao local

```powershell
py -3 -m uvicorn servidor.app:app --host 127.0.0.1 --port 8787
```

Para cadastrar uma chave manualmente no host, use
`py -3 tools/provisionar_licenca.py --assinatura-id ID_DO_PICPAY`. Sem
`--dias`, ela aguarda o webhook; nao copie o banco para o PC do jogador.

Antes de publicar, coloque TLS em um proxy reverso, use um gerenciador de
segredos e rode os testes do projeto. Nao coloque `.env`, banco ou chave
privada no Git.
