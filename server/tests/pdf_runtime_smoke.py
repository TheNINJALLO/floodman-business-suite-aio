from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from app.pdf_documents import build_estimate_pdf

JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAkAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD7LooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD//Z"


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="floodman-pdf-no-pillow-") as root:
        layout = Path(root) / "roomflow-layout.jpg"
        layout.write_bytes(base64.b64decode(JPEG_B64))
        estimate = {
            "id": "estimate-smoke",
            "estimate_number": "EST-SMOKE-462",
            "title": "Basement Waterproofing",
            "project_category": "basement-waterproofing",
            "project_summary": "Dependency-free PDF runtime validation.",
            "total_cents": 125000,
            "deposit_type": "PERCENT",
            "deposit_percent": 50,
            "roomflow_layout_path": str(layout),
            "sections": [{"id": "section-1", "name": "Waterproofing", "description": "Measured scope", "sort_order": 0}],
            "line_items": [{
                "id": "line-1", "section_id": "section-1", "section_name": "Waterproofing",
                "name": "Interior drainage", "description": "Measured RoomFlow line",
                "quantity": 25, "unit": "LF", "unit_price_cents": 5000,
                "line_total_cents": 125000, "sort_order": 0, "selected": True
            }],
        }
        pdf = build_estimate_pdf(
            estimate,
            {"name": "Floodman Test Customer", "email": "test@example.com"},
            {"service_street": "1 Test Way", "service_city": "Traverse City", "service_state": "MI", "service_postal_code": "49684"},
            {"created_by": "Josh Aldrich"},
        )
        assert pdf.startswith(b"%PDF-"), "Estimate output is not a PDF"
        assert b"/DCTDecode" in pdf, "RoomFlow JPEG was not embedded directly"
        assert len(pdf) > 3000, "Estimate PDF is unexpectedly small"
    print("Floodman dependency-free PDF smoke test passed")


if __name__ == "__main__":
    run()
