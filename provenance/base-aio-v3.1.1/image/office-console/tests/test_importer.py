from __future__ import annotations

import io
import zipfile

import pytest

from app.importer import ImportValidationError, create_zip, sample_files, unpack_zip, validate


def test_sample_import_is_valid_and_reconciles() -> None:
    files = sample_files()
    summary, normalized = validate(files)
    assert summary["valid"] is True
    assert summary["counts"] == {
        "contacts": 1,
        "properties": 1,
        "estimates": 1,
        "estimate_lines": 2,
        "invoices": 1,
        "payments": 1,
        "documents": 1,
        "notes": 1,
        "attachments": 3,
    }
    assert summary["totals"]["estimate_cents"] == 100_000
    assert summary["totals"]["estimate_line_cents"] == 100_000
    assert summary["totals"]["invoice_cents"] == 100_000
    assert summary["totals"]["payment_cents"] == 30_000
    assert summary["totals"]["outstanding_cents"] == 70_000
    assert normalized["contacts"][0]["email"] == "jane.sample@example.com"
    assert normalized["documents"][0]["_stored_file_path"] == "exports/documents/work-authorization-001.pdf"


@pytest.mark.parametrize("required", [
    "contacts.csv",
    "properties.csv",
    "estimates.csv",
    "estimate_lines.csv",
    "invoices.csv",
    "payments.csv",
])
def test_missing_required_file_is_reported(required: str) -> None:
    files = sample_files()
    del files[required]
    summary, _ = validate(files)
    assert summary["valid"] is False
    assert f"Missing required file: {required}" in summary["errors"]


def test_zip_path_traversal_is_rejected() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../contacts.csv", b"bad")
    with pytest.raises(ImportValidationError):
        unpack_zip(output.getvalue())


def test_sample_zip_round_trip() -> None:
    zipped = create_zip(sample_files())
    unpacked = unpack_zip(zipped)
    assert "contacts.csv" in unpacked
    assert "exports/invoices/invoice-001.pdf" in unpacked
    assert "exports/documents/work-authorization-001.pdf" in unpacked
