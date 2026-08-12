from __future__ import annotations

import html
import json
from typing import Any


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def money(cents: Any) -> str:
    try:
        amount = int(cents or 0) / 100
    except Exception:
        amount = 0
    return f"${amount:,.2f}"


BASE_CSS = r"""
:root{--navy:#12344b;--navy2:#0b2638;--blue:#129dcc;--green:#6bb82b;--magenta:#c70078;--ink:#162b3a;--muted:#6c7b88;--line:#d6e0e6;--pale:#edf7fb;--good:#eaf7e5;--danger:#fff0f4}
*{box-sizing:border-box}html{background:#edf4f8;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{margin:0}.shell{max-width:960px;margin:0 auto;padding:26px 20px 70px}.brand{display:flex;align-items:center;gap:14px;margin-bottom:18px}.drop{width:42px;height:54px;border:4px solid var(--blue);border-top-color:var(--green);border-right-color:var(--magenta);border-radius:54% 46% 54% 46%;transform:rotate(12deg)}.brand h1{margin:0;font-size:24px;letter-spacing:.08em;color:var(--navy)}.brand p{margin:2px 0 0;color:var(--muted);font-size:13px}.rule{height:4px;background:linear-gradient(90deg,var(--blue) 0 54%,var(--green) 54% 84%,var(--magenta) 84%);margin-bottom:22px}.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 10px 30px rgba(18,52,75,.06);margin:14px 0}.hero{background:linear-gradient(135deg,var(--navy2),#19658a);color:#fff}.hero h2{font-size:32px;margin:0 0 6px}.hero p{margin:0;color:#d9edf5}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.metric{border:1px solid var(--line);border-radius:12px;padding:14px;background:#fff}.metric small,.eyebrow{display:block;color:var(--muted);font-weight:800;letter-spacing:.08em;text-transform:uppercase;font-size:11px}.metric strong{display:block;margin-top:6px;color:var(--navy);font-size:21px}.button,button{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:10px;padding:13px 18px;background:var(--blue);color:#fff;font-weight:800;text-decoration:none;cursor:pointer;font-size:15px}.button.secondary{background:#e8f1f5;color:var(--navy)}.button.good,button.good{background:#198754}.button[aria-disabled="true"]{opacity:.45;pointer-events:none}.actions{display:flex;gap:10px;flex-wrap:wrap}.status{display:inline-flex;padding:6px 10px;border-radius:999px;background:#f8e8f1;color:var(--magenta);font-weight:800;font-size:12px}.status.paid{background:var(--good);color:#28711c}.group{border:1px solid var(--line);border-radius:13px;overflow:hidden;margin:14px 0}.group h3{margin:0;padding:12px 15px;background:#f0f5f8;color:var(--navy);font-size:15px}.line{display:grid;grid-template-columns:minmax(0,1fr) 100px 110px;gap:12px;padding:12px 15px;border-top:1px solid var(--line);align-items:start}.line strong{color:var(--navy)}.line small{display:block;color:var(--muted);margin-top:4px}.subtotal{display:flex;justify-content:space-between;background:#f7fafb;padding:10px 15px;font-weight:800}.payment-box{background:var(--pale);border:1px solid #c4e3ef;border-radius:14px;padding:18px}.notice{padding:13px;border-radius:10px;background:#f4f7f9;color:var(--muted);margin:12px 0}.notice.error{background:var(--danger);color:#912149}.notice.good{background:var(--good);color:#27641f}.field{margin:12px 0}.field label{display:block;font-size:12px;font-weight:800;color:var(--navy);margin-bottom:6px}.field input,.field select{width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;background:#fff;font-size:16px}.pay-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.footer{text-align:center;color:var(--muted);font-size:12px;margin-top:26px}.documents{display:grid;gap:8px}.documents a{color:var(--blue);font-weight:700}.print-link{float:right}.receipt{border-left:5px solid var(--green)}#card-container{min-height:90px;border:1px solid var(--line);border-radius:10px;padding:12px;background:#fff}.spinner{width:18px;height:18px;border:3px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;margin-right:8px}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:700px){.shell{padding:16px 12px 80px}.grid,.pay-row{grid-template-columns:1fr}.line{grid-template-columns:1fr 78px 90px;font-size:13px}.hero h2{font-size:27px}.brand h1{font-size:20px}.button,button{width:100%;min-height:48px}.actions{display:grid}.print-link{float:none;margin-top:8px}}
@media print{html{background:#fff}.shell{max-width:none;padding:0}.button,.actions,.print-link{display:none!important}.card{box-shadow:none;break-inside:avoid}.footer{margin-top:12px}}
"""


def page(title: str, body: str, *, scripts: str = "", extra_head: str = "") -> str:
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='robots' content='noindex,nofollow,noarchive'><title>{esc(title)} | Floodman</title><style>{BASE_CSS}</style>{extra_head}</head><body><main class='shell'><header class='brand'><div class='drop' aria-hidden='true'></div><div><h1>FLOODMAN</h1><p>Waterproofing - Foundation Repair - Restoration</p></div></header><div class='rule'></div>{body}<footer class='footer'>Floodman, LLC - Northern Michigan - (231) 935-4921 - office@floodman.com</footer></main>{scripts}</body></html>"""


def grouped_lines(groups: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for index, group in enumerate(groups, start=1):
        lines = []
        for line in group.get("lines") or []:
            if line.get("selected") is False:
                continue
            lines.append(
                f"<div class='line'><div><strong>{esc(line.get('name'))}</strong><small>{esc(line.get('description'))}</small></div><div>{esc(line.get('quantity'))} {esc(line.get('unit') or 'each')}</div><div style='text-align:right'>{money(line.get('line_total_cents'))}</div></div>"
            )
        if not lines:
            continue
        rendered.append(
            f"<section class='group'><h3>{index:02d} &nbsp; {esc(group.get('name'))}</h3>{''.join(lines)}<div class='subtotal'><span>{esc(group.get('name'))} subtotal</span><span>{money(group.get('subtotal_cents'))}</span></div></section>"
        )
    return "".join(rendered)


def payment_page(
    *,
    title: str,
    reference: str,
    amount_cents: int,
    max_amount_cents: int,
    currency: str,
    customer: dict[str, Any],
    process_url: str,
    return_url: str,
    config: dict[str, Any],
    staff_keyed: bool = False,
    allow_save: bool = True,
    allow_partial: bool = False,
) -> str:
    local_mock = bool(config.get("local_mock"))
    live = bool(config.get("live"))
    script_url = str(config.get("sdk_url") or "")
    app_id = str(config.get("application_id") or "")
    location_id = str(config.get("location_id") or "")
    minimum = 1
    amount_value = amount_cents / 100
    mode_note = "Card information is entered in a secure payment field and is never stored by Floodman."
    if staff_keyed:
        mode_note = "Enter the card while speaking with the customer. The secure field sends a one-time payment token; Floodman never stores the full card number or security code."
    if not live and not local_mock:
        config_notice = "<div class='notice error'><b>Payments need setup.</b> The Floodman payment processor application ID, access token, and location ID are not configured.</div>"
    elif local_mock:
        config_notice = "<div class='notice'><b>Test mode.</b> This button records a simulated payment so you can verify the complete Floodman workflow before production credentials are connected.</div>"
    else:
        config_notice = ""

    amount_field = f"<input id='payment-amount' type='number' min='{minimum/100:.2f}' max='{max_amount_cents/100:.2f}' step='0.01' value='{amount_value:.2f}' {'readonly' if not allow_partial else ''}>"
    save_box = ""
    if allow_save:
        save_box = "<label style='display:flex;gap:8px;align-items:flex-start;margin:12px 0;color:var(--muted)'><input id='save-card' type='checkbox' style='width:auto;margin-top:3px'> <span>Save this payment method for future charges that I separately authorize.</span></label>"
    auth_reference = ""
    if staff_keyed:
        auth_reference = "<div class='field'><label>Customer authorization reference</label><input id='authorization-reference' placeholder='Signed authorization, written request, or call note reference'></div>"

    body = f"""
<div class='card hero'><span class='eyebrow' style='color:#bfe3f0'>FLOODMAN SECURE PAYMENT</span><h2>{esc(title)}</h2><p>Reference {esc(reference)}</p></div>
<div class='grid'><div class='metric'><small>Amount requested</small><strong>{money(amount_cents)}</strong></div><div class='metric'><small>Maximum available</small><strong>{money(max_amount_cents)}</strong></div><div class='metric'><small>Payment status</small><strong>Ready</strong></div></div>
<div class='card'><h2>Card payment</h2><p>{esc(mode_note)}</p>{config_notice}<div class='field'><label>Amount</label>{amount_field}</div><div id='card-container'></div>{save_box}{auth_reference}<div id='payment-message' class='notice' style='display:none'></div><button id='pay-button' class='good' {'disabled' if not live and not local_mock else ''}>Pay {money(amount_cents)}</button><div class='actions' style='margin-top:12px'><a class='button secondary' href='{esc(return_url)}'>Return to document</a></div></div>
"""

    config_json = json.dumps({
        "appId": app_id,
        "locationId": location_id,
        "processUrl": process_url,
        "returnUrl": return_url,
        "currency": currency,
        "amountCents": amount_cents,
        "maxAmountCents": max_amount_cents,
        "localMock": local_mock,
        "staffKeyed": staff_keyed,
        "customer": {
            "givenName": customer.get("first_name") or str(customer.get("name") or "").split(" ")[0],
            "familyName": customer.get("last_name") or "",
            "email": customer.get("email") or customer.get("primaryEmail") or "",
            "phone": customer.get("phone") or customer.get("primaryPhone") or "",
            "addressLines": [customer.get("street") or customer.get("address") or ""],
            "city": customer.get("city") or "",
            "state": customer.get("state") or "",
            "postalCode": customer.get("postal_code") or "",
            "countryCode": customer.get("country") or "US",
        },
    })
    scripts = f"""
<script>window.FLOODMAN_PAYMENT={config_json};</script>
{f"<script src='{esc(script_url)}'></script>" if live else ''}
<script>
(async function(){{
  const cfg=window.FLOODMAN_PAYMENT;
  const btn=document.getElementById('pay-button');
  const msg=document.getElementById('payment-message');
  const amountInput=document.getElementById('payment-amount');
  let card=null;
  function show(text,kind){{msg.textContent=text;msg.style.display='block';msg.className='notice '+(kind||'');}}
  function cents(){{const value=Math.round(Number(amountInput.value||0)*100);return Math.max(1,Math.min(cfg.maxAmountCents,value));}}
  function setBusy(value){{btn.disabled=value;btn.innerHTML=value?'<span class="spinner"></span>Processing secure payment...':'Pay '+new Intl.NumberFormat('en-US',{{style:'currency',currency:cfg.currency}}).format(cents()/100);}}
  amountInput.addEventListener('input',()=>setBusy(false));
  if(!cfg.localMock){{
    try{{
      if(!window.Square) throw new Error('The secure payment field did not load. Check the HTTPS connection and try again.');
      const payments=window.Square.payments(cfg.appId,cfg.locationId);
      card=await payments.card();
      await card.attach('#card-container');
    }}catch(error){{show(error.message||String(error),'error');btn.disabled=true;}}
  }}
  btn.addEventListener('click',async()=>{{
    setBusy(true);show('Preparing payment...','');
    try{{
      let sourceId='LOCAL-MOCK-TOKEN';
      if(!cfg.localMock){{
        const amount=(cents()/100).toFixed(2);
        const details={{amount,currencyCode:cfg.currency,intent:document.getElementById('save-card')?.checked?'CHARGE_AND_STORE':'CHARGE',customerInitiated:!cfg.staffKeyed,sellerKeyedIn:cfg.staffKeyed,billingContact:cfg.customer}};
        const tokenResult=await card.tokenize(details);
        if(tokenResult.status!=='OK'){{throw new Error((tokenResult.errors||[]).map(e=>e.message).join(' ')||'The card could not be tokenized.');}}
        sourceId=tokenResult.token;
      }}
      const response=await fetch(cfg.processUrl,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:sourceId,amount_cents:cents(),save_card:Boolean(document.getElementById('save-card')?.checked),authorization_reference:document.getElementById('authorization-reference')?.value||'',staff_keyed:cfg.staffKeyed}})}});
      const data=await response.json().catch(()=>({{}}));
      if(!response.ok) throw new Error(data.detail||data.message||'Payment was not completed.');
      show(data.warning?'Payment completed. The payment method was not saved, but your Floodman receipt is ready.':'Payment completed. Your Floodman receipt is ready.','good');
      window.setTimeout(()=>window.location.assign(data.receipt_url||cfg.returnUrl),900);
    }}catch(error){{show(error.message||String(error),'error');setBusy(false);}}
  }});
}})();
</script>
"""
    return page(title, body, scripts=scripts)
