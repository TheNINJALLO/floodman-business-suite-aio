from __future__ import annotations

import io
import os
import re
import tempfile
import zipfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app import xactimate_catalog as catalog_module
from app.estimate_catalog import normalize_document_payload
from app.pdf_documents import build_estimate_pdf
from app.xactimate_catalog import (
    ProtectedXactimatePlxError,
    XactimateCatalogError,
    inspect_xactimate_plx,
    parse_xactimate_catalog_csv,
    parse_xactimate_catalog_upload,
    xactimate_catalog_template,
)


HEADERS = (
    "price_list,market_id,market,effective_date,category,category_name,selector,activity,"
    "description,unit,unit_price,material,labor,equipment,taxable,active\r\n"
)


def worksheet(price_list: str = "TESTMI_AUG26", unit_price: str = "12.34") -> bytes:
    rows = [
        f'{price_list},TESTMI,"Test City, MI",2026-08-01,WTR,Water Mitigation,DRY,,'
        f'Fictional drying equipment,day,{unit_price},2.00,8.00,2.34,no,yes',
        f'{price_list},TESTMI,"Test City, MI",,DMO,Demolition,DRYLF,REMOVE,'
        'Fictional drywall removal,SF,3.21,0.50,2.50,0.21,no,yes',
    ]
    return (HEADERS + "\r\n".join(rows) + "\r\n").encode("utf-8")


def protected_plx() -> bytes:
    output = io.BytesIO()
    opaque = bytes(range(256)) * 24
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("XACTDOC.ZIPXML", opaque)
    return output.getvalue()


def parser_smoke() -> None:
    template = xactimate_catalog_template()
    assert template.startswith(b"\xef\xbb\xbfprice_list,market_id")
    first = parse_xactimate_catalog_csv(worksheet(), "fictional-pricing.csv")
    assert first.summary["counts"]["items_ready"] == 2
    assert first.summary["counts"]["needs_review"] == 1
    assert first.summary["minimum_unit_price_cents"] == 321
    assert first.summary["maximum_unit_price_cents"] == 1234
    item = first.normalized["catalog_items"][0]
    assert item["source_id"] == "TESTMI|WTR|DRY|STANDARD"
    assert item["formula"]["xactimate"]["code"] == "WTR DRY"
    assert item["formula"]["xactimate"]["components_cents"] == {
        "material": 200,
        "labor": 800,
        "equipment": 234,
    }
    refreshed = parse_xactimate_catalog_csv(worksheet("TESTMI_SEP26", "13.45"), "fictional-pricing-refresh.csv")
    assert refreshed.normalized["catalog_items"][0]["source_id"] == item["source_id"]
    assert refreshed.normalized["catalog_items"][0]["unit_price_cents"] == 1345
    sections, lines, total = normalize_document_payload(
        {
            "sections": [{"id": "section-1", "name": "Water Mitigation"}],
            "line_items": [{
                "section_id": "section-1",
                "name": item["name"],
                "quantity": 2,
                "unit": item["unit"],
                "unit_price_cents": item["unit_price_cents"],
                "pricing_reference": item["formula"]["xactimate"]["code"],
                "pricing_price_list": item["formula"]["xactimate"]["price_list"],
                "pricing_effective_date": item["formula"]["xactimate"]["effective_date"],
            }],
        }
    )
    assert lines[0]["pricing_reference"] == "WTR DRY"
    pdf = build_estimate_pdf(
        {"estimate_number": "EST-TEST", "title": "Fictional estimate", "sections": sections, "line_items": lines, "total_cents": total},
        {"name": "Fictional Customer"},
        {"name": "Fictional Property"},
        {},
    )
    streams = []
    for match in re.finditer(rb"stream\n(.*?)\nendstream", pdf, re.DOTALL):
        try:
            streams.append(zlib.decompress(match.group(1)))
        except zlib.error:
            continue
    assert any(b"WTR DRY" in stream and b"12.34" in stream for stream in streams)

    try:
        parse_xactimate_catalog_csv(b"description,unit_price\nMissing identity,1.00\n", "bad.csv")
    except XactimateCatalogError as exc:
        assert "missing required columns" in str(exc)
    else:
        raise AssertionError("Pricing CSV without stable identity columns was accepted")

    try:
        parse_xactimate_catalog_csv(b"x" * (catalog_module.MAX_UPLOAD_BYTES + 1), "oversized.csv")
    except XactimateCatalogError as exc:
        assert "larger than the 25 MB" in str(exc)
    else:
        raise AssertionError("Oversized pricing CSV was accepted")

    original_max_rows = catalog_module.MAX_ROWS
    catalog_module.MAX_ROWS = 1
    try:
        try:
            parse_xactimate_catalog_csv(worksheet(), "too-many-rows.csv")
        except XactimateCatalogError as exc:
            assert "1-item safety limit" in str(exc)
        else:
            raise AssertionError("Pricing CSV row limit was not enforced")
    finally:
        catalog_module.MAX_ROWS = original_max_rows

    data = protected_plx()
    inspection = inspect_xactimate_plx(data, "fictional.plx")
    assert inspection.member_name == "XACTDOC.ZIPXML"
    assert inspection.member_size == 6144
    assert inspection.opaque_payload is True
    try:
        parse_xactimate_catalog_upload(data, "fictional.plx")
    except ProtectedXactimatePlxError as exc:
        assert exc.inspection.sha256 == inspection.sha256
        assert "supported Xactimate converter" in str(exc)
    else:
        raise AssertionError("Protected PLX was treated as decoded pricing")

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../XACTDOC.ZIPXML", b"opaque")
    try:
        inspect_xactimate_plx(unsafe.getvalue(), "unsafe.plx")
    except XactimateCatalogError as exc:
        assert "unsafe member path" in str(exc)
    else:
        raise AssertionError("Unsafe PLX member path was accepted")


def web_workflow_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="floodman-xactimate-") as temp:
        os.environ["OFFICE_CONSOLE_DATA_DIR"] = str(Path(temp) / "office")
        os.environ["DOCUMENTS_PATH"] = str(Path(temp) / "documents")
        os.environ["OFFICE_CONSOLE_PUBLIC_URL"] = "http://127.0.0.1"
        os.environ["FLOODMAN_CUSTOMER_PUBLIC_URL"] = "http://127.0.0.1/customer"
        os.environ["OFFICE_SESSION_COOKIE_SECURE"] = "false"
        os.environ["INTERNAL_HMAC_KEYS"] = "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
        os.environ["AI_HMAC_KEYS"] = "ai-v1:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
        from app import main

        main.store.create_owner("Pricing Test Owner", "pricing@example.test", "Floodman-Test-2026!")
        client = TestClient(main.app, follow_redirects=False)
        login = client.post(
            "/login",
            data={"email": "pricing@example.test", "password": "Floodman-Test-2026!", "next": "/office/catalog"},
        )
        assert login.status_code == 303

        catalog = client.get("/office/catalog")
        assert catalog.status_code == 200
        assert "Bring in licensed Xactimate pricing" in catalog.text
        assert "Download pricing CSV template" in catalog.text
        template = client.get("/office/catalog/import-xactimate/template.csv")
        assert template.status_code == 200 and template.content == xactimate_catalog_template()

        upload = client.post(
            "/office/catalog/import-xactimate",
            files={"pricing_file": ("fictional-pricing.csv", worksheet(), "text/csv")},
        )
        assert upload.status_code == 303 and upload.headers["location"].startswith("/office/imports/")
        review_path = upload.headers["location"]
        assert not main.store.records("catalog_items"), "Preview wrote catalog data before confirmation"
        review = client.get(review_path)
        assert review.status_code == 200
        assert "Nothing has been added yet" in review.text
        assert "WTR DRY" in review.text and "$12.34" in review.text

        committed = client.post(review_path + "/commit")
        assert committed.status_code == 303
        imported = [item for item in main.store.records("catalog_items") if item.get("source_provider") == "XACTIMATE_USER_IMPORT"]
        assert len(imported) == 2
        assert imported[0].get("formula", {}).get("xactimate")
        code_search = client.get("/office/api/catalog/items", params={"q": "WTR DRY"})
        assert code_search.status_code == 200 and code_search.json()["total"] == 1
        catalog_search = client.get("/office/catalog", params={"q": "WTR DRY"})
        assert catalog_search.status_code == 200 and "Fictional drying equipment" in catalog_search.text

        refresh = client.post(
            "/office/catalog/import-xactimate",
            files={"pricing_file": ("fictional-pricing-refresh.csv", worksheet("TESTMI_SEP26", "13.45"), "text/csv")},
        )
        assert refresh.status_code == 303
        refreshed_review = refresh.headers["location"]
        refreshed_commit = client.post(refreshed_review + "/commit")
        assert refreshed_commit.status_code == 303
        imported = [item for item in main.store.records("catalog_items") if item.get("source_provider") == "XACTIMATE_USER_IMPORT"]
        assert len(imported) == 2, "Repeat pricing import created duplicate items"
        drying = next(item for item in imported if item["source_id"] == "TESTMI|WTR|DRY|STANDARD")
        assert drying["unit_price_cents"] == 1345
        second_run = main.store.get_import(refreshed_review.rsplit("/", 1)[-1]) or {}
        assert (second_run.get("commit_result") or {}).get("updated") == 2

        import_count = len(main.store.list_imports())
        plx = client.post(
            "/office/catalog/import-xactimate",
            files={"pricing_file": ("fictional.plx", protected_plx(), "application/octet-stream")},
        )
        assert plx.status_code == 303 and plx.headers["location"] == "/office/catalog"
        assert len(main.store.list_imports()) == import_count, "Protected PLX was retained as an import"
        notice_page = client.get("/office/catalog")
        assert "PLX recognized" in notice_page.text and "was not stored or imported" in notice_page.text


def run() -> None:
    parser_smoke()
    web_workflow_smoke()
    print("Floodman Xactimate pricing inspection, preview, and stable update smoke test passed")


if __name__ == "__main__":
    run()
