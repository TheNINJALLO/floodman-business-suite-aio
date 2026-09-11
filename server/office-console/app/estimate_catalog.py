from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


DEFAULT_SECTION_NAME = "Scope of Work"
DEFAULT_UNIT = "each"


def clean_text(value: Any, limit: int = 5000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]



CATEGORY_LABELS = {
    "waterproofing": "Waterproofing",
    "mold-remediation": "Mold Remediation",
    "demolition-rebuild": "Demolition & Rebuild",
    "water-restoration": "Water Restoration",
    "landscaping-exterior": "Exterior & Site Work",
    "inspection-testing": "Inspection & Testing",
    "general-services": "General Services",
    "administrative": "Administrative & Fees",
    "disposal": "Landfill & Disposal Fees",
}


def category_label(value: Any) -> str:
    raw = clean_text(value, 120).lower()
    if not raw:
        return "General Services"
    if raw in CATEGORY_LABELS:
        return CATEGORY_LABELS[raw]
    return re.sub(r"[-_]+", " ", raw).title()


def slug(value: Any, limit: int = 72) -> str:
    text = clean_text(value, 300).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or "item")[:limit]


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid number: {value}") from exc


def money_to_cents(value: Any, *, already_cents: bool = False) -> int:
    amount = decimal_value(value)
    if already_cents:
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stable_catalog_id(source: str, source_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-catalog:{source}:{source_id}"))


def normalize_catalog_item(payload: dict[str, Any], *, source: str = "FLOODMAN_CUSTOM") -> dict[str, Any]:
    name = clean_text(payload.get("name") or payload.get("description"), 250)
    if not name:
        raise ValueError("Catalog item name is required.")
    category = clean_text(payload.get("category") or payload.get("default_section") or "General Services", 120)
    unit = clean_text(payload.get("unit") or DEFAULT_UNIT, 40) or DEFAULT_UNIT
    source_id = clean_text(payload.get("source_id") or payload.get("id") or payload.get("external_key"), 160)
    external_key = clean_text(payload.get("external_key"), 160)
    if not external_key:
        external_key = f"{source.lower()}:{slug(category)}:{slug(name)}:{slug(unit)}"
    if not source_id:
        source_id = external_key
    cents_value = payload.get("unit_price_cents")
    unit_price_cents = money_to_cents(cents_value, already_cents=True) if cents_value not in (None, "") else money_to_cents(payload.get("unit_price") or 0)
    internal_value = payload.get("internal_cost_cents")
    if internal_value in (None, "") and payload.get("internal_cost") not in (None, ""):
        internal_value = money_to_cents(payload.get("internal_cost"))
    internal_cost_cents = money_to_cents(internal_value, already_cents=True) if internal_value not in (None, "") else None
    return {
        "id": clean_text(payload.get("floodman_id"), 100) or stable_catalog_id(source, source_id),
        "external_key": external_key,
        "source_id": source_id,
        "source_provider": source,
        "organization_id": clean_text(payload.get("organization_id"), 100) or None,
        "name": name,
        "description": clean_text(payload.get("description"), 5000),
        "category": category or "General Services",
        "default_section": clean_text(payload.get("default_section"), 120) or category_label(category),
        "pricing_method": clean_text(payload.get("pricing_method") or "fixed", 50).lower() or "fixed",
        "unit": unit,
        "unit_price_cents": max(0, unit_price_cents),
        "internal_cost_cents": max(0, internal_cost_cents) if internal_cost_cents is not None else None,
        "taxable": bool(payload.get("taxable")),
        "active": payload.get("active") is not False,
        "review_required": bool(payload.get("review_required")),
        "review_notes": clean_text(payload.get("review_notes"), 1000),
        "formula": payload.get("formula") if isinstance(payload.get("formula"), dict) else {},
    }


def default_document(title: str = "") -> dict[str, Any]:
    section_id = str(uuid.uuid4())
    return {
        "sections": [{"id": section_id, "name": clean_text(title, 240) or DEFAULT_SECTION_NAME, "description": "", "sort_order": 0}],
        "line_items": [],
    }


def _section_id(raw: Any, index: int) -> str:
    value = clean_text(raw, 100)
    return value or str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-estimate-section:{index}:{uuid.uuid4()}"))


def _line_id(raw: Any) -> str:
    return clean_text(raw, 120) or str(uuid.uuid4())


def normalize_document_payload(value: Any, *, title: str = "", legacy_text: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("Estimate builder data was invalid. Reload the page and try again.") from exc
        else:
            payload = {}
    elif isinstance(value, dict):
        payload = value
    else:
        payload = {}

    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    raw_lines = payload.get("line_items") if isinstance(payload.get("line_items"), list) else []

    # Backward compatibility with the old Description | Quantity | Price textarea.
    if not raw_lines and legacy_text.strip():
        section_name = clean_text(title, 240) or DEFAULT_SECTION_NAME
        section_id = str(uuid.uuid4())
        raw_sections = [{"id": section_id, "name": section_name, "sort_order": 0}]
        for number, raw in enumerate(legacy_text.splitlines(), start=1):
            if not raw.strip():
                continue
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) < 3:
                raise ValueError(f"Line {number} must use Description | Quantity | Unit price")
            raw_lines.append({
                "section_id": section_id,
                "name": parts[0],
                "quantity": parts[1],
                "unit_price": parts[2],
                "sort_order": number - 1,
                "custom": True,
            })

    if not raw_sections:
        raw_sections = default_document(title)["sections"]

    sections: list[dict[str, Any]] = []
    section_lookup: dict[str, dict[str, Any]] = {}
    section_names: dict[str, str] = {}
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            continue
        section_id = _section_id(raw.get("id"), index)
        name = clean_text(raw.get("name") or raw.get("section_name"), 240) or f"Section {index + 1}"
        record = {
            "id": section_id,
            "name": name,
            "description": clean_text(raw.get("description"), 2000),
            "sort_order": int(raw.get("sort_order") if str(raw.get("sort_order", "")).lstrip("-").isdigit() else index),
        }
        sections.append(record)
        section_lookup[section_id] = record
        section_names[section_id] = name

    sections.sort(key=lambda item: (int(item.get("sort_order") or 0), item["name"].casefold()))
    valid_ids = {item["id"] for item in sections}
    fallback_id = sections[0]["id"]

    lines: list[dict[str, Any]] = []
    total_cents = 0
    for index, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            continue
        name = clean_text(raw.get("name") or raw.get("description"), 250)
        if not name:
            continue
        section_id = clean_text(raw.get("section_id"), 100)
        if section_id not in valid_ids:
            requested_name = clean_text(raw.get("section_name"), 240)
            matched = next((item["id"] for item in sections if requested_name and item["name"].casefold() == requested_name.casefold()), None)
            section_id = matched or fallback_id
        quantity = decimal_value(raw.get("quantity"), Decimal("1"))
        if quantity <= 0:
            raise ValueError(f"{name}: quantity must be greater than zero.")
        unit_cents_raw = raw.get("unit_price_cents")
        unit_price_cents = money_to_cents(unit_cents_raw, already_cents=True) if unit_cents_raw not in (None, "") else money_to_cents(raw.get("unit_price") or raw.get("price") or 0)
        if unit_price_cents < 0:
            raise ValueError(f"{name}: unit price cannot be negative.")
        line_total_cents = int((quantity * Decimal(unit_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        selected = raw.get("selected") is not False
        if selected:
            total_cents += line_total_cents
        section_name = section_names.get(section_id, DEFAULT_SECTION_NAME)
        catalog_item_id = clean_text(raw.get("catalog_item_id"), 120) or None
        record = {
            "id": _line_id(raw.get("id") or raw.get("line_id") or raw.get("roomflow_line_id")),
            "section_id": section_id,
            "section_name": section_name,
            "catalog_item_id": catalog_item_id,
            "name": name,
            "description": clean_text(raw.get("description"), 5000),
            "quantity": float(quantity),
            "unit": clean_text(raw.get("unit") or DEFAULT_UNIT, 40) or DEFAULT_UNIT,
            "unit_price_cents": unit_price_cents,
            "line_total_cents": line_total_cents,
            "price": unit_price_cents / 100,
            "totalValue": line_total_cents / 100,
            "taxable": bool(raw.get("taxable")),
            "optional": bool(raw.get("optional")),
            "selected": selected,
            "pricing_method": clean_text(raw.get("pricing_method") or "fixed", 50).lower(),
            "sort_order": int(raw.get("sort_order") if str(raw.get("sort_order", "")).lstrip("-").isdigit() else index),
            "category": clean_text(raw.get("category") or section_name, 120),
            "pricing_reference": clean_text(raw.get("pricing_reference"), 160),
            "pricing_source": clean_text(raw.get("pricing_source"), 120),
            "pricing_price_list": clean_text(raw.get("pricing_price_list"), 160),
            "pricing_effective_date": clean_text(raw.get("pricing_effective_date"), 80),
            "pricing_market": clean_text(raw.get("pricing_market"), 200),
            "custom": bool(raw.get("custom") or not catalog_item_id),
            "save_to_catalog": bool(raw.get("save_to_catalog") or raw.get("custom") or not catalog_item_id),
        }
        lines.append(record)

    if not lines:
        raise ValueError("Add at least one line item.")
    lines.sort(key=lambda item: (next((int(sec.get("sort_order") or 0) for sec in sections if sec["id"] == item["section_id"]), 0), int(item.get("sort_order") or 0)))
    return sections, lines, total_cents


def document_payload(document: dict[str, Any]) -> dict[str, Any]:
    sections = document.get("sections") if isinstance(document.get("sections"), list) else []
    lines = document.get("line_items") if isinstance(document.get("line_items"), list) else []
    if not sections:
        default = default_document(str(document.get("title") or ""))
        sections = default["sections"]
        section_id = sections[0]["id"]
        lines = [{**line, "section_id": line.get("section_id") or section_id, "section_name": line.get("section_name") or sections[0]["name"]} for line in lines]
    return {"sections": sections, "line_items": lines}


def group_document_lines(document: dict[str, Any]) -> list[dict[str, Any]]:
    payload = document_payload(document)
    sections = sorted(payload["sections"], key=lambda item: int(item.get("sort_order") or 0))
    lines = payload["line_items"]
    groups: list[dict[str, Any]] = []
    for section in sections:
        section_lines = [line for line in lines if str(line.get("section_id") or "") == str(section.get("id") or "")]
        if not section_lines:
            section_lines = [line for line in lines if str(line.get("section_name") or "").casefold() == str(section.get("name") or "").casefold()]
        section_lines.sort(key=lambda item: int(item.get("sort_order") or 0))
        groups.append({**section, "lines": section_lines, "subtotal_cents": sum(int(item.get("line_total_cents") or 0) for item in section_lines if item.get("selected") is not False)})
    ungrouped = [line for line in lines if not any(line in group["lines"] for group in groups)]
    if ungrouped:
        groups.append({"id": "ungrouped", "name": "Additional Items", "description": "", "sort_order": len(groups), "lines": ungrouped, "subtotal_cents": sum(int(item.get("line_total_cents") or 0) for item in ungrouped if item.get("selected") is not False)})
    return groups
