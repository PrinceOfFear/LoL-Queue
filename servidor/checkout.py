"""Pagina externa de checkout do LoL Queue.

O navegador coleta os dados do cartao apenas para entrega imediata ao SDK
oficial do PicPay. O backend recebe somente o temporaryCardToken.
"""

from __future__ import annotations

import json
import secrets


def render_checkout(
    *,
    api_base_url: str,
    merchant_credential: str,
    transparent_token: str,
    sdk_url: str,
) -> tuple[str, str]:
    """Renderiza uma pagina sem interpolar valores em HTML executavel."""
    config = json.dumps(
        {
            "apiBase": api_base_url,
            "merchantCredential": merchant_credential,
            "transparentToken": transparent_token,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    sdk = json.dumps(sdk_url, ensure_ascii=True)
    nonce = secrets.token_urlsafe(18)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LoL Queue — assinatura mensal</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, Segoe UI, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: radial-gradient(circle at 20% 10%, #123c55, #06131f 55%, #030910); color: #e8f5ff; }}
    main {{ width: min(100% - 32px, 560px); padding: 32px; border: 1px solid #1d526d;
      border-radius: 24px; background: rgba(5, 24, 38, .94); box-shadow: 0 24px 80px #0008; }}
    .brand {{ color: #57d7ff; letter-spacing: .16em; font-size: 12px; font-weight: 800; }}
    h1 {{ margin: 10px 0 6px; font-size: clamp(27px, 5vw, 38px); }}
    .sub {{ color: #a9c2d3; margin: 0 0 22px; line-height: 1.5; }}
    .price {{ display: flex; align-items: baseline; gap: 8px; padding: 16px; border-radius: 14px;
      background: linear-gradient(110deg, #0a3952, #0a263a); margin-bottom: 20px; }}
    .price strong {{ font-size: 30px; color: #64e6bc; }}
    form {{ display: grid; gap: 13px; }}
    label {{ display: grid; gap: 6px; color: #cbe4f1; font-size: 13px; }}
    input, select {{ width: 100%; border: 1px solid #2c5a72; border-radius: 10px; background: #061726;
      color: #f3fbff; padding: 12px; font: inherit; }}
    input:focus, select:focus {{ outline: 2px solid #39c6e8; outline-offset: 1px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    button {{ border: 0; border-radius: 12px; padding: 14px; color: #03121b; background: #54ddbb;
      font-weight: 800; cursor: pointer; margin-top: 6px; }}
    button:disabled {{ cursor: wait; opacity: .6; }}
    .notice {{ min-height: 22px; margin-top: 14px; color: #a9c2d3; line-height: 1.45; }}
    .notice.error {{ color: #ff9e9e; }} .notice.ok {{ color: #64e6bc; }}
    .small {{ margin-top: 17px; color: #7e9aab; font-size: 12px; line-height: 1.45; }}
    @media (max-width: 480px) {{ main {{ padding: 22px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <div class="brand">LOL QUEUE · LICENÇA OFICIAL</div>
  <h1>Jogue com tudo preparado.</h1>
  <p class="sub">Assinatura mensal com ativação automática após a confirmação do PicPay.</p>
  <div class="price"><strong>R$ 20,00</strong><span>por mês · renovação recorrente</span></div>
  <form id="checkout-form" autocomplete="off">
    <label>Nome completo<input name="name" required maxlength="255" autocomplete="name"></label>
    <label>E-mail<input name="email" type="email" required maxlength="254" autocomplete="email"></label>
    <div class="grid">
      <label>CPF<input name="document" required inputmode="numeric" pattern="\\d{{11}}" maxlength="11"></label>
      <label>Celular<input name="phone" required inputmode="numeric" pattern="\\d{{10,11}}" maxlength="11"></label>
    </div>
    <label>Nome no cartão<input name="holderName" required maxlength="120" autocomplete="cc-name"></label>
    <label>Número do cartão<input name="number" required inputmode="numeric" pattern="\\d{{13,16}}" maxlength="16" autocomplete="cc-number"></label>
    <div class="grid">
      <label>Validade (mês)<input name="expirationMonth" required inputmode="numeric" pattern="\\d{{1,2}}" maxlength="2" autocomplete="cc-exp-month"></label>
      <label>Validade (ano)<input name="expirationYear" required inputmode="numeric" pattern="\\d{{4}}" maxlength="4" autocomplete="cc-exp-year"></label>
    </div>
    <label>CVV<input name="cvv" required inputmode="numeric" pattern="\\d{{3,4}}" maxlength="4" autocomplete="cc-csc"></label>
    <button id="submit" type="submit">Criar assinatura segura</button>
  </form>
  <div id="notice" class="notice" role="status" aria-live="polite"></div>
  <div class="small">O LoL Queue não recebe nem armazena os dados do cartão. O PicPay gera um token temporário e o pagamento só libera a licença depois do webhook autenticado.</div>
</main>
<script nonce="{nonce}" src={sdk} crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<script nonce="{nonce}">
const CONFIG = {config};
const form = document.getElementById('checkout-form');
const button = document.getElementById('submit');
const notice = document.getElementById('notice');
function message(text, kind = '') {{ notice.textContent = text; notice.className = 'notice ' + kind; }}
function digits(value) {{ return String(value || '').replace(/\\D/g, ''); }}
function responseMessage(body) {{
  return body && body.detail ? String(body.detail) : 'Não foi possível iniciar a assinatura.';
}}
form.addEventListener('submit', async (event) => {{
  event.preventDefault(); button.disabled = true; message('Protegendo os dados do cartão no PicPay…');
  const data = Object.fromEntries(new FormData(form).entries());
  const phone = digits(data.phone);
  try {{
    if (!window.CheckoutTransparent) throw new Error('SDK do PicPay ainda não carregou.');
    CheckoutTransparent.setCredentials({{ merchantCredential: CONFIG.merchantCredential, transparentToken: CONFIG.transparentToken }});
    const brand = await new Promise((resolve, reject) => CheckoutTransparent.getCardBrand({{
      bin: digits(data.number).slice(0, 6), success: resolve, error: reject
    }}));
    const tokenBody = await new Promise((resolve, reject) => CheckoutTransparent.createTemporaryCard({{
      card: {{ brand: brand.brand, number: digits(data.number), holderName: data.holderName,
        holderDocument: digits(data.document), expirationMonth: data.expirationMonth,
        expirationYear: data.expirationYear, cvv: digits(data.cvv) }}, success: resolve, error: reject
    }}));
    const token = tokenBody.temporaryToken || tokenBody.temporaryCardToken;
    if (!token) throw new Error('O PicPay não devolveu um token temporário.');
    const response = await fetch((CONFIG.apiBase || '') + '/api/assinaturas', {{
      method: 'POST', headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
      body: JSON.stringify({{ name: data.name, email: data.email, document_type: 'CPF', document: digits(data.document),
        phone: {{ country_code: '55', area_code: phone.slice(0, 2), number: phone.slice(2), type: 'MOBILE' }}, card_token: token }})
    }});
    const body = await response.json().catch(() => ({{}}));
    if (!response.ok) throw new Error(responseMessage(body));
    if (!body.chave || typeof body.chave !== 'string') throw new Error('O servidor não devolveu a chave da assinatura.');
    form.reset(); message('Assinatura criada. A licença será ativada automaticamente após a confirmação do PicPay. Guarde sua chave: ' + body.chave, 'ok');
  }} catch (error) {{ message(error && error.message ? error.message : 'Falha ao processar o pagamento.', 'error'); }}
  finally {{ button.disabled = false; }}
}});
</script>
</body>
</html>""", nonce
