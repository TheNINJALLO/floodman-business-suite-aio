from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any


SOURCE_PROVIDER = "XACTIMATE_USER_IMPORT"
IMPORT_KIND = "XACTIMATE_CATALOG_CSV"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_PLX_BYTES = 100 * 1024 * 1024
MAX_ROWS = 50_000
MAX_CELL_LENGTH = 5_000


class XactimateCatalogError(ValueError):
    pass


class ProtectedXactimatePlxError(XactimateCatalogError):
    def __init__(self, message: str, inspection: "PlxInspection") -> None:
        super().__init__(message)
        self.inspection = inspection


@dataclass(frozen=True)
class PlxInspection:
    filename: str
    sha256: str
    member_name: str
    member_size: int
    member_sha256: str
    opaque_payload: bool


@dataclass(frozen=True)
class CatalogParseResult:
    summary: dict[str, Any]
    normalized: dict[str, Any]


HEADER_ALIASES = {
    "price_list": {"pricelist", "pricelistname", "pricelistid", "listname"},
    "market_id": {"marketid", "regionid", "marketcode", "regioncode"},
    "market": {"market", "location", "region", "city"},
    "effective_date": {"effectivedate", "published", "publishdate", "pricingdate", "listdate"},
    "category": {"category", "cat", "categorycode"},
    "category_name": {"categoryname", "section", "sectionname"},
    "selector": {"selector", "sel", "selectorcode", "itemcode", "code"},
    "activity": {"activity", "act", "activitycode"},
    "description": {"description", "itemdescription", "name", "itemname"},
    "unit": {"unit", "uom", "unitofmeasure"},
    "unit_price": {"unitprice", "price", "unitcost", "totalunitprice"},
    "material": {"material", "materials", "materialcost"},
    "labor": {"labor", "labour", "laborcost", "labourcost"},
    "equipment": {"equipment", "equipmentcost"},
    "taxable": {"taxable", "tax"},
    "active": {"active", "enabled"},
}

REQUIRED_FIELDS = ("price_list", "category", "selector", "description", "unit", "unit_price")


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _clean(value: Any, limit: int = MAX_CELL_LENGTH) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(str(value or fallback).replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f\"]+", "_", name).strip(" .")
    return (name or fallback)[:240]


def _identity_part(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", _clean(value, 200).upper()).strip("-")


def _market_key(price_list: str, market_id: str, market: str) -> str:
    if market_id:
        return _identity_part(market_id)
    value = _identity_part(price_list)
    value = re.sub(
        r"-(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)-?\d{2,4}$",
        "",
        value,
    )
    return value or _identity_part(market) or "UNSPECIFIED-MARKET"


def _money_cents(value: str, *, row_number: int, field: str) -> int | None:
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise XactimateCatalogError(f"Row {row_number}: {field} must be a dollar amount.") from exc
    if amount < 0 or amount > Decimal("99999999.99"):
        raise XactimateCatalogError(f"Row {row_number}: {field} is outside the supported range.")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _boolean(value: str, *, default: bool, row_number: int, field: str) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise XactimateCatalogError(f"Row {row_number}: {field} must be yes or no.")


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise XactimateCatalogError("The PLX contains an unsafe member path.")
    return normalized


def _looks_opaque(data: bytes) -> bool:
    if not data:
        return False
    sample = data[: min(len(data), 256 * 1024)]
    printable = sum(byte in {9, 10, 13} or 32 <= byte <= 126 for byte in sample)
    return printable / len(sample) < 0.80 and not sample.lstrip().startswith((b"<?xml", b"<"))


def inspect_xactimate_plx(data: bytes, filename: str) -> PlxInspection:
    safe_name = _safe_filename(filename, "price-list.plx")
    if not data:
        raise XactimateCatalogError("The selected PLX is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise XactimateCatalogError("The selected file is larger than the 25 MB pricing-import limit.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XactimateCatalogError("The selected file is not a valid Xactimate PLX container.") from exc
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if not members or len(members) > 10:
            raise XactimateCatalogError("The PLX has an unexpected number of files.")
        total_size = 0
        for member in members:
            _safe_member_name(member.filename)
            total_size += int(member.file_size)
            if total_size > MAX_UNCOMPRESSED_PLX_BYTES:
                raise XactimateCatalogError("The PLX expands beyond the 100 MB safety limit.")
            compressed = max(1, int(member.compress_size))
            if member.file_size > 5 * 1024 * 1024 and member.file_size / compressed > 100:
                raise XactimateCatalogError("The PLX has an unsafe compression ratio.")
        member = next((item for item in members if Path(item.filename).name.casefold() == "xactdoc.zipxml"), None)
        if member is None:
            raise XactimateCatalogError("Floodman did not find the expected XACTDOC.ZIPXML member in this PLX.")
        try:
            payload = archive.read(member)
        except (RuntimeError, NotImplementedError) as exc:
            payload = b""
            opaque = True
        else:
            opaque = _looks_opaque(payload)
    return PlxInspection(
        filename=safe_name,
        sha256=hashlib.sha256(data).hexdigest(),
        member_name=_safe_member_name(member.filename),
        member_size=int(member.file_size),
        member_sha256=hashlib.sha256(payload).hexdigest() if payload else "",
        opaque_payload=opaque or bool(member.flag_bits & 0x1),
    )


def _decode_csv(data: bytes) -> str:
    if not data:
        raise XactimateCatalogError("The selected pricing CSV is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise XactimateCatalogError("The selected file is larger than the 25 MB pricing-import limit.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise XactimateCatalogError("Save the pricing worksheet as UTF-8 or Windows CSV and try again.")


def _column_mapping(headers: list[str]) -> dict[str, str]:
    normalized_headers = {_header_key(header): header for header in headers if _header_key(header)}
    mapping: dict[str, str] = {}
    for target, aliases in HEADER_ALIASES.items():
        source = next((normalized_headers[alias] for alias in aliases if alias in normalized_headers), None)
        if source:
            mapping[target] = source
    missing = [field.replace("_", " ") for field in REQUIRED_FIELDS if field not in mapping]
    if missing:
        raise XactimateCatalogError(
            "The pricing CSV is missing required columns: " + ", ".join(missing) + ". Download the Floodman template and keep its headers."
        )
    return mapping


def parse_xactimate_catalog_csv(data: bytes, filename: str) -> CatalogParseResult:
    safe_name = _safe_filename(filename, "xactimate-pricing.csv")
    text = _decode_csv(data)
    try:
        dialect = csv.Sniffer().sniff(text[:16_384], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    headers = [_clean(value, 200) for value in (reader.fieldnames or []) if _clean(value, 200)]
    if not headers:
        raise XactimateCatalogError("The pricing CSV does not contain a header row.")
    mapping = _column_mapping(headers)

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    identities: set[str] = set()
    categories: set[str] = set()
    price_lists: set[str] = set()
    markets: set[str] = set()
    effective_dates: set[str] = set()
    minimum_price: int | None = None
    maximum_price: int | None = None

    for row_index, raw in enumerate(reader, start=2):
        if row_index > MAX_ROWS + 1:
            raise XactimateCatalogError(f"The pricing CSV exceeds the {MAX_ROWS:,}-item safety limit.")
        row = {target: _clean(raw.get(source), MAX_CELL_LENGTH) for target, source in mapping.items()}
        if not any(row.values()):
            continue
        missing_values = [field.replace("_", " ") for field in REQUIRED_FIELDS if not row.get(field)]
        if missing_values:
            raise XactimateCatalogError(f"Row {row_index}: missing " + ", ".join(missing_values) + ".")

        unit_price_cents = _money_cents(row["unit_price"], row_number=row_index, field="unit price")
        assert unit_price_cents is not None
        components = {
            key: _money_cents(row.get(key, ""), row_number=row_index, field=key)
            for key in ("material", "labor", "equipment")
        }
        category_code = row["category"].upper()
        selector = row["selector"].upper()
        activity = row.get("activity", "").upper()
        price_list = row["price_list"]
        market = row.get("market", "")
        market_key = _market_key(price_list, row.get("market_id", ""), market)
        source_id = "|".join((_identity_part(market_key), _identity_part(category_code), _identity_part(selector), _identity_part(activity or "STANDARD")))
        if source_id in identities:
            raise XactimateCatalogError(
                f"Row {row_index}: duplicate category/selector/activity identity {category_code} {selector} {activity or 'STANDARD'}."
            )
        identities.add(source_id)
        effective_date = row.get("effective_date", "")
        if not effective_date and len(warnings) < 100:
            warnings.append(f"Row {row_index}: no effective date was supplied; verify this price before sending an estimate.")
        category_name = row.get("category_name", "") or category_code
        taxable = _boolean(row.get("taxable", ""), default=False, row_number=row_index, field="taxable")
        active = _boolean(row.get("active", ""), default=True, row_number=row_index, field="active")
        code = f"{category_code} {selector}" + (f" {activity}" if activity else "")
        item = {
            "external_key": f"xactimate:{source_id.lower()}",
            "source_id": source_id,
            "source_provider": SOURCE_PROVIDER,
            "name": row["description"],
            "description": row["description"],
            "category": category_name,
            "default_section": category_name,
            "unit": row["unit"],
            "unit_price_cents": unit_price_cents,
            "taxable": taxable,
            "active": active,
            "review_required": not bool(effective_date),
            "review_notes": "Confirm the licensed source price and effective date before sending." if not effective_date else "",
            "formula": {
                "xactimate": {
                    "code": code,
                    "price_list": price_list,
                    "market_id": market_key,
                    "market": market,
                    "effective_date": effective_date,
                    "category": category_code,
                    "selector": selector,
                    "activity": activity,
                    "components_cents": {key: value for key, value in components.items() if value is not None},
                }
            },
        }
        items.append(item)
        categories.add(category_name)
        price_lists.add(price_list)
        if market:
            markets.add(market)
        if effective_date:
            effective_dates.add(effective_date)
        minimum_price = unit_price_cents if minimum_price is None else min(minimum_price, unit_price_cents)
        maximum_price = unit_price_cents if maximum_price is None else max(maximum_price, unit_price_cents)

    if not items:
        raise XactimateCatalogError("The pricing CSV does not contain any line items.")
    source_sha256 = hashlib.sha256(data).hexdigest()
    summary = {
        "import_kind": IMPORT_KIND,
        "source_filename": safe_name,
        "source_sha256": source_sha256,
        "included_files": [safe_name],
        "headers": headers,
        "column_mapping": mapping,
        "counts": {
            "rows_read": len(items),
            "items_ready": len(items),
            "categories": len(categories),
            "price_lists": len(price_lists),
            "markets": len(markets),
            "needs_review": sum(1 for item in items if item["review_required"]),
        },
        "price_lists": sorted(price_lists, key=str.casefold),
        "markets": sorted(markets, key=str.casefold),
        "effective_dates": sorted(effective_dates, key=str.casefold),
        "minimum_unit_price_cents": minimum_price or 0,
        "maximum_unit_price_cents": maximum_price or 0,
        "warnings": warnings,
        "errors": [],
    }
    return CatalogParseResult(
        summary=summary,
        normalized={
            "import_kind": IMPORT_KIND,
            "source_sha256": source_sha256,
            "catalog_items": items,
        },
    )


def parse_xactimate_catalog_upload(data: bytes, filename: str) -> CatalogParseResult:
    safe_name = _safe_filename(filename, "pricing-import")
    looks_zip = data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if safe_name.lower().endswith(".plx") or looks_zip:
        inspection = inspect_xactimate_plx(data, safe_name)
        qualifier = "protected/opaque" if inspection.opaque_payload else "undocumented"
        raise ProtectedXactimatePlxError(
            "Floodman recognized this Xactimate PLX, but its XACTDOC.ZIPXML payload is "
            f"{qualifier} and cannot be imported safely without a supported Xactimate converter. "
            "Open the PLX through Xactimate Data Transfer, then place the licensed line-item values in the Floodman pricing CSV template.",
            inspection,
        )
    if not safe_name.lower().endswith(".csv"):
        raise XactimateCatalogError("Choose an Xactimate .plx file to inspect or a Floodman pricing .csv file to preview.")
    return parse_xactimate_catalog_csv(data, safe_name)


def xactimate_catalog_template() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        (
            "price_list",
            "market_id",
            "market",
            "effective_date",
            "category",
            "category_name",
            "selector",
            "activity",
            "description",
            "unit",
            "unit_price",
            "material",
            "labor",
            "equipment",
            "taxable",
            "active",
        )
    )
    return ("\ufeff" + output.getvalue()).encode("utf-8")
