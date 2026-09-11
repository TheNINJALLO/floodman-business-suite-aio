from __future__ import annotations

import html
from typing import Any

from .call_intake import CallIntakeProjectionRequest


def approval_form(store: Any, record: dict[str, Any], selected_customer_id: str = "") -> str:
    esc = lambda value: html.escape(str(value or ""), quote=True)
    if record.get("approval_status") == "APPROVED":
        portal = esc(record.get("portal_sync_status") or "PENDING")
        erp = esc(record.get("erp_sync_status") or "PENDING")
        error = esc(record.get("portal_sync_error") or "")
        link = f"<a class='button secondary' href='{esc(record['portal_url'])}' target='_blank' rel='noopener'>Open photo portal</a>" if record.get("portal_url") else ""
        return f"<section class='card'><h2>Customer files approved</h2><p>Photo portal: {portal} · ERP: {erp}</p>{f'<p>{error}</p>' if error else ''}{link}</section>"
    workspace = str(record.get("workspace_id") or "")
    customers = [row for row in store.records("contacts") if str(row.get("workspace_id") or "") == workspace]
    selected = next((row for row in customers if str(row['id']) == selected_customer_id), None)
    selected_customer_id = str(selected['id']) if selected else ""
    properties = [row for row in store.records("properties") if selected and str(row.get("contact_id") or "") == selected_customer_id and str(row.get("workspace_id") or "") == workspace]
    caller = dict(record.get("caller") or {})
    prop = dict(record.get("property") or {})
    if selected:
        caller.update({key: selected.get(key) or caller.get(key) or "" for key in ("name", "email", "phone")})
    options = "<option value=''>Create customer from this call</option>" + "".join(
        f"<option value='{esc(row['id'])}' {'selected' if str(row['id']) == selected_customer_id else ''}>{esc(row.get('name') or row['id'])}</option>" for row in customers)
    property_options = "<option value=''>Create property from the address below</option>" + "".join(
        f"<option value='{esc(row['id'])}'>{esc(row.get('service_street') or row.get('name') or row['id'])}</option>" for row in properties)
    fields = []
    for key, label, value, required in [
        ("name", "Customer name", caller.get("name"), True), ("email", "Email", caller.get("email"), False),
        ("phone", "Phone", caller.get("phone_e164") or caller.get("phone"), True),
        ("street", "Street address", prop.get("street"), True), ("city", "City", prop.get("city"), True),
        ("state", "State", prop.get("state"), True), ("postal_code", "ZIP code", prop.get("postal_code"), True),
    ]:
        browser_required = required and (not properties or key in ('name', 'phone'))
        readonly = selected is not None and key in ('name', 'email', 'phone')
        fields.append(f"<div class='field'><label for='approve-{key}'>{label}</label><input id='approve-{key}' name='{key}' value='{esc(value)}' maxlength='320' {'required' if browser_required else ''} {'readonly' if readonly else ''}></div>")
    return (
        "<section class='card'><h2>Review and approve</h2><p>Confirm the customer and service address before creating linked files.</p>"
        f"<form method='get' action='/office/calls/{esc(record['id'])}'><div class='field'><label for='approve-customer'>Customer</label><select id='approve-customer' name='customer_id'>{options}</select></div><button class='secondary'>Choose customer</button></form>"
        f"<form method='post' action='/office/calls/{esc(record['id'])}/approve'><input type='hidden' name='customer_id' value='{esc(selected_customer_id)}'>"
        f"<div class='field'><label for='approve-property'>Property</label><select id='approve-property' name='property_id'>{property_options}</select></div>"
        "<p class='muted'>Choose an existing property, or confirm the address below to create one. Existing customer details are kept.</p>"
        "<div class='form-grid three'>" + "".join(fields) + "</div>"
        "<button style='margin-top:16px'>Approve and create customer files</button></form></section>"
    )


def approve_call(store: Any, record: dict[str, Any], actor_id: str, values: dict[str, str]) -> dict[str, Any]:
    if record.get("approval_status") == "APPROVED":
        return record
    payload = {key: record[key] for key in CallIntakeProjectionRequest.model_fields if key in record}
    caller = dict(payload.get("caller") or {})
    prop = dict(payload.get("property") or {})
    workspace = str(record.get("workspace_id") or "")
    customer_id = values.get("customer_id", "").strip()
    property_id = values.get("property_id", "").strip()
    if customer_id:
        customer = store.record("contacts", customer_id)
        if not customer or str(customer.get("workspace_id") or "") != workspace:
            raise ValueError("Choose a customer from this workspace.")
        caller.update({key: str(customer.get(key) or values.get(key) or "") for key in ("name", "email", "phone")})
    else:
        caller.update({key: values.get(key, "").strip() for key in ("name", "email", "phone")})
        parts = caller['name'].split(None, 1)
        caller['first_name'] = parts[0] if parts else ''
        caller['last_name'] = parts[1] if len(parts) > 1 else ''
    caller['phone_e164'] = caller['phone']
    # Human approval confirms record selection, not telephone ownership for billing.
    caller['phone_verified'] = False
    if not caller.get('name') or not caller.get('phone'):
        raise ValueError("Customer name and phone are required.")
    if property_id:
        selected = store.record("properties", property_id)
        if not selected or str(selected.get('contact_id') or '') != customer_id or str(selected.get('workspace_id') or '') != workspace:
            raise ValueError("Choose a property belonging to the selected customer.")
        prop.update({key: str(selected.get('service_' + key) or selected.get(key) or '') for key in ('street','city','state','postal_code')})
    else:
        prop.update({key: values.get(key, '').strip() for key in ('street','city','state','postal_code')})
    if not all(prop.get(key) for key in ('street','city','state','postal_code')):
        raise ValueError("Confirm the full service address, including city, state, and ZIP code.")
    payload.update({'caller': caller, 'property': prop})
    validated = CallIntakeProjectionRequest.model_validate(payload).model_dump(mode='json')
    return store.project_call_intake(validated, actor_id=actor_id, approved_by=actor_id,
                                    selected_customer_id=customer_id, selected_property_id=property_id)
