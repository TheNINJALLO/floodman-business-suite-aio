from __future__ import annotations

import html
import json
from typing import Any, Iterable

from .auth import has_permission


NAV_GROUPS = [
    ("Command", [
        ("/office", "Command Center", "dashboard", "dashboard.view"),
        ("/office/apps", "All Applications", "apps", "apps.view"),
        ("/office/gauzy", "Full Gauzy ERP", "gauzy", "apps.view"),
        ("/office/signing", "Signing Suite", "signing", "documents.view"),
    ]),
    ("Customers & Jobs", [
        ("/office/contacts", "Contacts", "contacts", "contacts.view"),
        ("/office/properties", "Properties", "properties", "properties.view"),
        ("/office/tasks", "Tasks", "tasks", "tasks.view"),
        ("/office/notes", "Notes", "notes", "notes.view"),
    ]),
    ("Sales & Billing", [
        ("/office/estimates", "Estimates", "estimates", "estimates.view"),
        ("/office/invoices", "Invoices", "invoices", "invoices.view"),
        ("/office/payments", "Payments", "payments", "payments.view"),
        ("/office/receivables", "Receivables", "receivables", "receivables.view"),
    ]),
    ("People & Communication", [
        ("/office/time", "Time Clock", "time", "time.self"),
        ("/office/members", "Members & Roles", "members", "members.manage"),
        ("/office/documents", "Documents & Signing", "documents", "documents.view"),
        ("/office/messages", "Messages", "messages", "messages.view"),
        ("/office/alerts", "Staff Alerts", "alerts", "alerts.view"),
    ]),
    ("Growth & Administration", [
        ("/office/intelligence", "AI Competitor Intelligence", "intelligence", "intelligence.view"),
        ("/office/imports", "Import Center", "imports", "imports.manage"),
        ("/office/linking", "Connections", "linking", "connections.manage"),
        ("/setup", "Setup", "setup", "connections.manage"),
    ]),
]


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def money_cents(value: Any, currency: str = "USD") -> str:
    try:
        cents = int(value or 0)
    except (TypeError, ValueError):
        cents = 0
    prefix = "$" if str(currency).upper() == "USD" else f"{esc(currency)} "
    return f"{prefix}{cents / 100:,.2f}"


def money_units(value: Any, currency: str = "USD") -> str:
    try:
        units = float(value or 0)
    except (TypeError, ValueError):
        units = 0
    prefix = "$" if str(currency).upper() == "USD" else f"{esc(currency)} "
    return f"{prefix}{units:,.2f}"


def badge(value: Any, tone: str | None = None) -> str:
    text = str(value or "UNKNOWN")
    normalized = text.upper()
    if tone is None:
        if normalized in {"CONNECTED", "READY", "PAID", "ACTIVE", "COMPLETED", "ACCEPTED", "OPTED_IN", "FULLY_PAID", "OWNER"}:
            tone = "good"
        elif normalized in {"FAILED", "INVALID", "DISABLED", "DEAD", "DISPUTED", "PAST_DUE", "ERROR"}:
            tone = "bad"
        elif normalized in {"PREVIEWED", "PENDING", "INVITED", "QUEUED", "PARTIALLY_PAID", "WARNING", "UNPAID", "RUNNING"}:
            tone = "warn"
        else:
            tone = "neutral"
    return f"<span class='badge {tone}'>{esc(text)}</span>"


def progress(checklist: dict[str, bool]) -> tuple[int, int, int]:
    keys = ["owner_created", "profile_saved", "connections_tested", "import_reviewed", "legal_reviewed", "messaging_reviewed"]
    done = sum(1 for key in keys if checklist.get(key))
    return done, len(keys), int(done / len(keys) * 100)


def json_pre(value: Any) -> str:
    return f"<pre>{esc(json.dumps(value, indent=2, default=str))}</pre>"


def table(headers: Iterable[str], rows: Iterable[Iterable[Any]], empty: str = "No records yet.") -> str:
    header_values = list(headers)
    row_values = list(rows)
    head = "".join(f"<th>{esc(value)}</th>" for value in header_values)
    if not row_values:
        body = f"<tr><td colspan='{len(header_values)}' class='empty'>{esc(empty)}</td></tr>"
    else:
        body = "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in row_values)
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def simple_page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)} · Floodman Office</title><style>{BASE_CSS}</style></head><body><div class='auth-shell'><div class='auth-card'><div class='brand big'>Floodman Office</div>{body}</div></div></body></html>"""


BASE_CSS = r"""
:root{--bg:#07111f;--panel:#101d2f;--panel2:#15263d;--line:#29415f;--text:#edf4ff;--muted:#9fb0c6;--accent:#32a7ff;--accent2:#67d5c4;--danger:#ff7878;--warn:#ffc65c;--good:#5be39d}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% -10%,#193b5e 0,#07111f 44%);color:var(--text);font-family:Segoe UI,Arial,sans-serif;min-height:100vh}a{color:#8bd3ff;text-decoration:none}a:hover{text-decoration:underline}.shell{display:grid;grid-template-columns:265px minmax(0,1fr);min-height:100vh}aside{background:#081426ee;border-right:1px solid var(--line);padding:18px 13px;position:sticky;top:0;height:100vh;overflow:auto}.brand{font-size:21px;font-weight:800;letter-spacing:.2px;margin:3px 8px 4px}.brand.big{font-size:28px;margin:0 0 18px}.subbrand{font-size:12px;color:var(--muted);margin:0 8px 18px}.nav-group{margin:15px 0 5px;padding:0 10px;color:#7792b0;font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:800}nav a{display:block;padding:9px 11px;border-radius:9px;color:#cfe0f4;margin:2px 0;font-weight:600;font-size:14px}nav a:hover{background:#162b45;text-decoration:none}nav a.active{background:#1c5f91;color:white;box-shadow:inset 3px 0 0 #8dd6ff}.side-note{margin-top:17px;border:1px solid #5c512d;background:#2a2516;padding:11px;border-radius:10px;font-size:12px;color:#f5d984}.user-box{margin-top:18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#0a1728}.user-box strong{display:block}.user-box form{margin-top:9px}main{padding:24px 30px 50px;min-width:0}header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}h1{font-size:31px;margin:0 0 5px}h2{font-size:20px;margin:0 0 14px}h3{font-size:16px;margin:0 0 10px}.muted{color:var(--muted)}.card{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 0 16px;box-shadow:0 14px 35px #0004}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.metric strong{display:block;font-size:27px;margin-top:7px}.metric small{color:var(--muted)}.app-card{display:flex;flex-direction:column;min-height:170px}.app-card .actions{margin-top:auto}.badge{display:inline-block;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:750;border:1px solid #50657e;background:#1e3149}.badge.good{color:#9ff4c9;border-color:#25744e;background:#0b3827}.badge.warn{color:#ffe1a1;border-color:#806321;background:#453312}.badge.bad{color:#ffc0c0;border-color:#873e3e;background:#471c24}.badge.neutral{color:#c9d7e8}.notice{border:1px solid #276d8d;background:#0d3044;border-radius:11px;padding:12px 14px;margin-bottom:16px;color:#bfeaff}.callout{border-left:4px solid var(--accent);background:#0b2035;padding:13px 15px;border-radius:8px;margin:12px 0}.warning{border-left-color:var(--warn);background:#2a2516}.danger{border-left-color:var(--danger);background:#351b22}.success{border-left-color:var(--good);background:#0b2d22}button,.button{display:inline-block;background:#1888d4;color:white;border:0;border-radius:9px;padding:10px 14px;font-weight:750;cursor:pointer;text-decoration:none}button:hover,.button:hover{filter:brightness(1.12);text-decoration:none}.button.secondary,button.secondary{background:#263e59}.button.good,button.good{background:#16754a}.button.danger,button.danger{background:#8b3540}.button.small,button.small{padding:7px 10px;font-size:12px}label{display:block;font-size:13px;color:#c8d8ea;margin:0 0 6px}input,select,textarea{width:100%;background:#081426;color:var(--text);border:1px solid #46617f;border-radius:8px;padding:10px 11px;font:inherit}textarea{min-height:100px;resize:vertical}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.form-grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}.field.full{grid-column:1/-1}.checks label{display:flex;gap:9px;align-items:flex-start;margin:9px 0}.checks input{width:auto;margin-top:3px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px}table{width:100%;border-collapse:collapse;min-width:700px}th,td{padding:10px 12px;border-bottom:1px solid #263c58;text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:#a9bdd4;background:#0a1728}td{font-size:14px}tr:last-child td{border-bottom:0}.empty{text-align:center;color:var(--muted);padding:24px}pre{white-space:pre-wrap;word-break:break-word;background:#06101d;border:1px solid #233a57;border-radius:9px;padding:12px;max-height:460px;overflow:auto}code{background:#071321;border:1px solid #28425f;border-radius:5px;padding:2px 5px}details{border:1px solid #29415f;border-radius:9px;padding:10px;margin:8px 0;background:#0a1728}summary{cursor:pointer;font-weight:700}.progress{height:12px;border-radius:999px;background:#091525;border:1px solid #29415f;overflow:hidden}.progress span{display:block;height:100%;background:linear-gradient(90deg,#1686d2,#5bd6bc)}.steps{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-top:9px}.step{text-align:center;font-size:12px;color:var(--muted);padding:7px;border-radius:7px;background:#0a1728}.step.done{color:#a7f0ce;background:#0d3528}.actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.right{text-align:right}hr{border:0;border-top:1px solid var(--line);margin:18px 0}.mono{font-family:Consolas,monospace}.pill-list{display:flex;flex-wrap:wrap;gap:7px}.list-clean{margin:0;padding-left:20px}.auth-shell{min-height:100vh;display:grid;place-items:center;padding:20px}.auth-card{width:min(540px,100%);background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:28px;box-shadow:0 22px 60px #0008}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px}.tabs a{padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:#0a1728}.tabs a.active{background:#1c5f91;color:white}.split{display:grid;grid-template-columns:2fr 1fr;gap:16px}
@media(max-width:900px){.shell{display:block}aside{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}nav{display:flex;overflow:auto;gap:4px}.nav-group{display:none}nav a{white-space:nowrap}main{padding:20px 14px}.form-grid,.form-grid.three,.grid.two,.split{grid-template-columns:1fr}header{display:block}.header-meta{margin-top:10px}}
"""


def layout(
    title: str,
    content: str,
    *,
    active: str = "dashboard",
    notice: str = "",
    setup_complete: bool = False,
    release: str = "",
    user: dict[str, Any] | None = None,
) -> str:
    nav_parts: list[str] = []
    for group, items in NAV_GROUPS:
        visible = [item for item in items if user is None or has_permission(user, item[3])]
        if not visible:
            continue
        nav_parts.append(f"<div class='nav-group'>{esc(group)}</div>")
        nav_parts.extend(
            f"<a class={'active' if key == active else ''!r} href='{href}'>{esc(label)}</a>"
            for href, label, key, _permission in visible
        )
    nav = "".join(nav_parts)
    notice_html = f"<div class='notice'>{esc(notice)}</div>" if notice else ""
    setup_chip = badge("Setup complete", "good") if setup_complete else badge("Setup in progress", "warn")
    if user:
        user_box = (
            f"<div class='user-box'><strong>{esc(user.get('name'))}</strong><span class='muted'>{esc(user.get('email'))}</span>"
            f"<div style='margin-top:7px'>{badge(user.get('role'))}</div>"
            "<form method='post' action='/logout'><button class='secondary small'>Sign out</button></form></div>"
        )
    else:
        user_box = ""
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{esc(title)} · Floodman Office</title><style>{BASE_CSS}</style></head><body><div class='shell'><aside>
<div class='brand'>Floodman Office</div><div class='subbrand'>Full Operations Lab · {esc(release)}</div><nav>{nav}</nav>
<div class='side-note'><b>LOCAL BUSINESS STAGING</b><br>Gauzy runs in clean non-demo mode. Square, SMS, customer email, and signatures remain local or sandboxed until explicitly connected.</div>{user_box}
</aside><main><header><div><h1>{esc(title)}</h1><div class='muted'>One command center for Floodman operations, Gauzy ERP, signing, receivables, RoomFlow and AI intelligence.</div></div><div class='header-meta'>{setup_chip}</div></header>{notice_html}{content}</main></div></body></html>"""
