from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any


def make_pdf(title: str, body: str) -> bytes:
    """Build a tiny valid one-page PDF without external libraries."""
    safe_title = title.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    safe_body = body.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = (
        "BT /F1 18 Tf 72 720 Td (" + safe_title + ") Tj "
        "0 -36 Td /F1 11 Tf (" + safe_body + ") Tj ET"
    ).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def twilio_signature(auth_token: str, url: str, params: dict[str, Any]) -> str:
    value = url
    for key in sorted(params):
        raw = params[key]
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        for item in values:
            value += f"{key}{'' if item is None else item}"
    digest = hmac.new(auth_token.encode(), value.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


_START_READY_STATES = {"DEPOSIT_PAID"}
_START_WAIT_STATES = {"AUTHORIZATION_SIGNED", "DEPOSIT_PUBLISHED"}
_START_ALREADY_STATES = {
    "IN_PROGRESS",
    "CHANGE_ORDER_PENDING",
    "COMPLETION_SENT",
    "COMPLETION_SIGNED",
    "FINAL_PAYMENT_DUE",
    "PAID",
    "CLOSED",
}


def classify_start_state(value: str) -> str:
    """Classify the current workflow state for the local Start work button."""
    state = str(value or "").strip().upper()
    if state in _START_READY_STATES:
        return "READY"
    if state in _START_WAIT_STATES:
        return "WAIT"
    if state in _START_ALREADY_STATES:
        return "ALREADY_STARTED"
    return "BLOCKED"
