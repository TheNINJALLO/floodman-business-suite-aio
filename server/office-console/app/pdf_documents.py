from __future__ import annotations

import math
import re
import struct
import textwrap
import zlib
from pathlib import Path

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from .estimate_catalog import group_document_lines
from .project_plans import merge_project_plan



def _jpeg_info(data: bytes) -> tuple[int, int, int]:
    """Return JPEG width, height, and component count without decoding pixels."""
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise ValueError("RoomFlow layout is not a JPEG image.")
    offset = 2
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    standalone = {0x01, *range(0xD0, 0xD9)}
    length = len(data)
    while offset < length:
        while offset < length and data[offset] != 0xFF:
            offset += 1
        while offset < length and data[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break
        marker = data[offset]
        offset += 1
        if marker in standalone:
            continue
        if offset + 2 > length:
            break
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > length:
            break
        if marker in sof_markers:
            if segment_length < 8:
                break
            height, width = struct.unpack_from(">HH", data, offset + 3)
            components = data[offset + 7]
            if width <= 0 or height <= 0 or components not in {1, 3}:
                raise ValueError("RoomFlow JPEG uses an unsupported image layout.")
            return width, height, components
        offset += segment_length
    raise ValueError("Could not read the RoomFlow JPEG dimensions.")


PAGE_W = 612.0
PAGE_H = 792.0
MARGIN = 42.0
NAVY = (0.070, 0.180, 0.270)
BLUE = (0.050, 0.620, 0.800)
GREEN = (0.420, 0.720, 0.180)
MAGENTA = (0.780, 0.000, 0.470)
LIGHT_BLUE = (0.910, 0.970, 0.990)
LIGHT_GRAY = (0.955, 0.965, 0.975)
MID_GRAY = (0.440, 0.500, 0.550)
DARK = (0.090, 0.160, 0.220)
WHITE = (1.0, 1.0, 1.0)
PALE_GREEN = (0.925, 0.975, 0.900)
PALE_PINK = (0.990, 0.920, 0.960)


def _ascii(value: Any) -> str:
    text = str(value or "")
    substitutions = {
        "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u00b7": "-",
        "\u00a0": " ", "\u2026": "...", "\u2264": "<=", "\u2265": ">=",
    }
    for old, new in substitutions.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_escape(value: Any) -> str:
    return _ascii(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _money(cents: Any) -> str:
    try:
        amount = int(cents or 0) / 100
    except Exception:
        amount = 0
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _date(value: Any, fallback: str = "") -> str:
    if not value:
        return fallback
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return text[:32]
    return dt.strftime("%b %-d, %Y") if hasattr(dt, "strftime") else str(value)


def _contact_name(contact: dict[str, Any]) -> str:
    return str(
        contact.get("name")
        or contact.get("company")
        or " ".join(part for part in (contact.get("first_name"), contact.get("last_name")) if part)
        or "Customer"
    ).strip()


def _contact_email(contact: dict[str, Any]) -> str:
    return str(contact.get("email") or contact.get("primaryEmail") or "").strip()


def _contact_phone(contact: dict[str, Any]) -> str:
    return str(contact.get("phone") or contact.get("primaryPhone") or "").strip()


def _property_lines(record: dict[str, Any]) -> list[str]:
    street = str(record.get("service_street") or record.get("street") or "").strip()
    city = str(record.get("service_city") or record.get("city") or "").strip()
    state = str(record.get("service_state") or record.get("state") or "").strip()
    postal = str(record.get("service_postal_code") or record.get("postal_code") or "").strip()
    location = ", ".join(part for part in (city, " ".join(part for part in (state, postal) if part)) if part)
    label = str(record.get("property_type") or record.get("name") or record.get("property_name") or "Service property").strip()
    return [part for part in (street, location, label) if part]


def calculate_deposit(estimate: dict[str, Any]) -> tuple[int, str]:
    total = int(estimate.get("total_cents") or 0)
    mode = str(estimate.get("deposit_type") or ("PERCENT" if float(estimate.get("deposit_percent") or 0) > 0 else "NONE")).upper()
    if mode == "FIXED":
        amount = max(0, min(total, int(estimate.get("deposit_fixed_cents") or 0)))
        label = "Deposit requested"
    elif mode == "PERCENT":
        percent = max(0.0, min(100.0, float(estimate.get("deposit_percent") or 50.0)))
        amount = int(round(total * percent / 100.0))
        label = f"{percent:g}% deposit"
    else:
        amount = 0
        label = "No deposit required"
    return amount, label


@dataclass
class Page:
    commands: list[str]
    annotations: list[tuple[float, float, float, float, str]]


class PdfCanvas:
    def __init__(self) -> None:
        self.pages: list[Page] = []
        self.images: list[dict[str, Any]] = []
        self.page = self.new_page()

    def new_page(self) -> Page:
        page = Page([], [])
        self.pages.append(page)
        self.page = page
        return page

    def raw(self, command: str) -> None:
        self.page.commands.append(command)

    def fill(self, color: tuple[float, float, float]) -> None:
        self.raw(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg")

    def stroke(self, color: tuple[float, float, float]) -> None:
        self.raw(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG")

    def rect(self, x: float, y: float, w: float, h: float, *, fill: tuple[float, float, float] | None = None, stroke: tuple[float, float, float] | None = None, width: float = 1.0) -> None:
        if fill:
            self.fill(fill)
        if stroke:
            self.stroke(stroke)
        self.raw(f"{width:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re {'B' if fill and stroke else 'f' if fill else 'S'}")

    def line(self, x1: float, y1: float, x2: float, y2: float, *, color: tuple[float, float, float] = NAVY, width: float = 1.0) -> None:
        self.stroke(color)
        self.raw(f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def text(self, x: float, y: float, value: Any, *, size: float = 10, font: str = "F1", color: tuple[float, float, float] = DARK) -> None:
        self.fill(color)
        self.raw(f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(value)}) Tj ET")

    def right_text(self, right: float, y: float, value: Any, *, size: float = 10, font: str = "F1", color: tuple[float, float, float] = DARK) -> None:
        # Helvetica average width is close enough for business document alignment.
        estimate = len(_ascii(value)) * size * (0.52 if font == "F1" else 0.56)
        self.text(max(MARGIN, right - estimate), y, value, size=size, font=font, color=color)

    def link(self, x: float, y: float, w: float, h: float, url: str) -> None:
        target = str(url or "").strip()
        if target.startswith(("https://", "http://")):
            self.page.annotations.append((x, y, w, h, target))

    def image(self, x: float, y: float, w: float, h: float, source: Any, *, fit: str = "contain") -> bool:
        """Embed a JPEG-compatible image without adding a runtime PDF dependency."""
        if not source:
            return False
        try:
            if isinstance(source, (bytes, bytearray)):
                raw = bytes(source)
            else:
                path = Path(str(source))
                if not path.is_file():
                    return False
                raw = path.read_bytes()
            # Native RoomFlow captures are JPEG. Read their dimensions from the
            # JPEG headers and embed the bytes directly, so Floodman never imports
            # or installs Pillow in the Pterodactyl runtime.
            iw, ih, components = _jpeg_info(raw)
            data = raw
            name = f"Im{len(self.images) + 1}"
            self.images.append({
                "name": name,
                "data": data,
                "width": iw,
                "height": ih,
                "color_space": "/DeviceGray" if components == 1 else "/DeviceRGB",
            })
            if fit == "cover":
                scale = max(w / iw, h / ih)
            else:
                scale = min(w / iw, h / ih)
            dw, dh = iw * scale, ih * scale
            dx, dy = x + (w - dw) / 2, y + (h - dh) / 2
            self.raw(f"q {dw:.2f} 0 0 {dh:.2f} {dx:.2f} {dy:.2f} cm /{name} Do Q")
            return True
        except Exception:
            return False

    def wrapped(self, x: float, y: float, value: Any, *, width: float, size: float = 9, leading: float | None = None, font: str = "F1", color: tuple[float, float, float] = DARK, max_lines: int | None = None) -> float:
        leading = leading or size * 1.28
        chars = max(8, int(width / (size * 0.52)))
        paragraphs = _ascii(value).splitlines() or [""]
        lines: list[str] = []
        for paragraph in paragraphs:
            if not paragraph.strip():
                lines.append("")
            else:
                lines.extend(textwrap.wrap(paragraph, width=chars, break_long_words=False, replace_whitespace=True) or [""])
        if max_lines is not None:
            lines = lines[:max_lines]
        for line in lines:
            self.text(x, y, line, size=size, font=font, color=color)
            y -= leading
        return y

    def build(self) -> bytes:
        objects: list[bytes] = []

        def add(content: bytes) -> int:
            objects.append(content)
            return len(objects)

        font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        font3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>")
        image_entries: dict[str, int] = {}
        for image in self.images:
            data = image["data"]
            image_entries[image["name"]] = add(
                (
                    f"<< /Type /XObject /Subtype /Image /Width {image['width']} /Height {image['height']} "
                    f"/ColorSpace {image.get('color_space', '/DeviceRGB')} /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n"
                ).encode("ascii") + data + b"\nendstream"
            )
        page_entries: list[int] = []
        content_entries: list[int] = []
        annotation_entries: list[list[int]] = []
        for page in self.pages:
            stream = "\n".join(page.commands).encode("latin-1", "replace")
            compressed = zlib.compress(stream, level=6)
            content_entries.append(add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed) + compressed + b"\nendstream"))
            annotation_ids: list[int] = []
            for x, y, w, h, url in page.annotations:
                annotation_ids.append(add(
                    (f"<< /Type /Annot /Subtype /Link /Rect [{x:.2f} {y:.2f} {x+w:.2f} {y+h:.2f}] "
                     f"/Border [0 0 0] /A << /S /URI /URI ({_pdf_escape(url)}) >> >>").encode("latin-1", "replace")
                ))
            annotation_entries.append(annotation_ids)
            page_entries.append(add(b"PENDING"))
        pages_id = add(b"PENDING")
        catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
        for index, page_id in enumerate(page_entries):
            annotations = annotation_entries[index]
            annots = f" /Annots [{' '.join(f'{item} 0 R' for item in annotations)}]" if annotations else ""
            xobjects = ""
            if image_entries:
                xobjects = " /XObject << " + " ".join(f"/{name} {obj_id} 0 R" for name, obj_id in image_entries.items()) + " >>"
            objects[page_id - 1] = (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
                f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R /F3 {font3} 0 R >>{xobjects} >> "
                f"/Contents {content_entries[index]} 0 R{annots} >>"
            ).encode()
        kids = " ".join(f"{pid} 0 R" for pid in page_entries)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_entries)} >>".encode()

        out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{number} 0 obj\n".encode())
            out.extend(obj)
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(objects)+1}\n".encode())
        out.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            out.extend(f"{offset:010d} 00000 n \n".encode())
        out.extend(
            f"trailer\n<< /Size {len(objects)+1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        )
        return bytes(out)


def _brand_header(c: PdfCanvas, doc_type: str, number: str, status: str) -> None:
    # Abstract Floodman droplet mark.
    c.fill(BLUE)
    c.raw("64 741 m 54 721 58 706 68 699 c 78 706 82 720 72 739 c f")
    c.fill(MAGENTA)
    c.raw("70 729 m 64 714 66 704 72 699 c 79 704 81 714 75 726 c f")
    c.text(90, 742, "FLOODMAN", size=19, font="F2", color=NAVY)
    c.text(90, 725, "Waterproofing - Foundation Repair - Restoration", size=8.5, font="F2", color=MID_GRAY)
    c.text(90, 711, "Northern Michigan  |  (231) 935-4921  |  office@floodman.com", size=8, color=MID_GRAY)
    c.right_text(570, 742, doc_type, size=17, font="F2", color=NAVY)
    c.right_text(570, 724, number, size=9, color=MID_GRAY)
    c.right_text(570, 706, status, size=8.5, font="F2", color=MAGENTA if "DUE" in status or "REVIEW" in status else GREEN)
    c.line(42, 690, 350, 690, color=BLUE, width=3)
    c.line(350, 690, 480, 690, color=GREEN, width=3)
    c.line(480, 690, 570, 690, color=MAGENTA, width=3)


def _footer(c: PdfCanvas, number: str, page: int, pages: Any) -> None:
    c.line(42, 36, 570, 36, color=(0.82, 0.84, 0.86), width=0.8)
    c.text(42, 22, "Floodman, LLC - floodman.com - (231) 935-4921", size=7, font="F2", color=MID_GRAY)
    c.right_text(570, 22, f"{number}  |  Page {page} of {pages}", size=7, color=MID_GRAY)




def _finalize_page_count(c: PdfCanvas, placeholder: str = "__TOTAL_PAGES__") -> None:
    total = str(len(c.pages))
    for page in c.pages:
        page.commands[:] = [command.replace(placeholder, total) for command in page.commands]

def _info_box(c: PdfCanvas, x: float, y: float, w: float, h: float, label: str, lines: Iterable[str]) -> None:
    c.rect(x, y, w, h, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.8)
    c.text(x + 10, y + h - 16, label.upper(), size=7.3, font="F2", color=MID_GRAY)
    cursor = y + h - 32
    for i, line in enumerate(lines):
        c.text(x + 10, cursor, line, size=9 if i else 10, font="F2" if i == 0 else "F1", color=NAVY if i == 0 else MID_GRAY)
        cursor -= 14


def _section_rows(c: PdfCanvas, groups: list[dict[str, Any]], *, start_y: float, end_y: float, page_number: int, total_pages: int, number: str) -> tuple[int, float]:
    y = start_y
    section_index = 0
    for group in groups:
        lines = list(group.get("lines") or [])
        if not lines:
            continue
        needed = 24 + sum(29 + (7 if len(_ascii(line.get("description") or "")) > 115 else 0) for line in lines) + 22
        if y - needed < end_y:
            _footer(c, number, page_number, total_pages)
            c.new_page()
            page_number += 1
            _brand_header(c, "PROJECT ESTIMATE", number, "READY FOR REVIEW")
            c.text(42, 658, "DETAILED SCOPE OF WORK", size=8, font="F2", color=MID_GRAY)
            c.text(42, 640, "Included services, materials, and quantities", size=13, font="F2", color=NAVY)
            y = 612
        section_index += 1
        c.rect(42, y - 20, 528, 20, fill=LIGHT_GRAY, stroke=(0.82, 0.86, 0.89), width=0.6)
        c.text(52, y - 14, f"{section_index:02d}  {str(group.get('name') or 'SCOPE').upper()}", size=8.5, font="F2", color=NAVY)
        y -= 20
        for line in lines:
            description = str(line.get("description") or "")
            line_h = 29 + (7 if len(description) > 115 else 0)
            c.rect(42, y - line_h, 528, line_h, fill=WHITE, stroke=(0.86, 0.88, 0.90), width=0.5)
            c.text(52, y - 12, line.get("name") or "Service", size=8.5, font="F2", color=NAVY)
            if description:
                c.wrapped(52, y - 23, description, width=360, size=6.7, leading=8.2, color=MID_GRAY, max_lines=2)
            quantity = f"{line.get('quantity') or 0:g} {line.get('unit') or 'each'}"
            c.right_text(470, y - 15, quantity, size=7.5, color=DARK)
            c.right_text(560, y - 15, _money(line.get("line_total_cents") or 0), size=8, color=NAVY)
            y -= line_h
        c.rect(42, y - 18, 528, 18, fill=(0.965, 0.975, 0.980), stroke=(0.82, 0.86, 0.89), width=0.5)
        c.text(52, y - 12, f"{group.get('name') or 'Section'} subtotal", size=7.5, font="F2", color=MID_GRAY)
        c.right_text(560, y - 12, _money(group.get("subtotal_cents") or 0), size=8.5, font="F2", color=NAVY)
        y -= 22
    return page_number, y


def build_estimate_pdf(estimate: dict[str, Any], contact: dict[str, Any], property_record: dict[str, Any], profile: dict[str, Any], *, public_url: str = "", payments: list[dict[str, Any]] | None = None) -> bytes:
    estimate = merge_project_plan(estimate)
    plan = estimate.get("project_plan") if isinstance(estimate.get("project_plan"), dict) else {}
    c = PdfCanvas()
    groups = group_document_lines(estimate)
    number = str(estimate.get("estimate_number") or estimate.get("id") or "ESTIMATE")
    total = int(estimate.get("total_cents") or 0)
    deposit, deposit_label = calculate_deposit(estimate)
    deposit_paid = int(estimate.get("deposit_paid_cents") or 0)
    deposit_due = max(0, deposit - deposit_paid)
    balance = max(0, total - deposit_paid)
    issue = _date(estimate.get("issued_at") or estimate.get("created_at"), _date(datetime.now(UTC)))
    expiry_days = int(estimate.get("expiration_days") or 30)
    try:
        issued_dt = datetime.fromisoformat(str(estimate.get("issued_at") or estimate.get("created_at") or datetime.now(UTC).isoformat()).replace("Z", "+00:00"))
        valid_through = _date(issued_dt + timedelta(days=expiry_days))
    except Exception:
        valid_through = "30 days from issue"

    # Page 1
    _brand_header(c, "PROJECT ESTIMATE", number, "READY FOR REVIEW")
    _info_box(c, 42, 604, 160, 70, "Prepared for", [_contact_name(contact), _contact_email(contact), _contact_phone(contact)])
    _info_box(c, 210, 604, 200, 70, "Service property", _property_lines(property_record)[:3])
    _info_box(c, 418, 604, 152, 70, "Estimate details", [f"Issued {issue}", f"Valid through {valid_through}", f"Prepared by {estimate.get('prepared_by') or 'Josh Aldrich'}"])
    c.rect(42, 456, 340, 130, fill=NAVY)
    c.text(58, 562, "RECOMMENDED PROJECT PLAN", size=7.5, font="F2", color=(0.65, 0.82, 0.90))
    c.wrapped(58, 540, estimate.get("title") or "Floodman property restoration plan", width=300, size=17, leading=19, font="F2", color=WHITE, max_lines=3)
    c.wrapped(58, 482, estimate.get("project_summary") or estimate.get("summary") or "A clear scope of work prepared for the service property, including labor, material, equipment, protection, cleanup, and documentation.", width=300, size=8.4, leading=11.5, color=WHITE, max_lines=4)
    c.rect(392, 456, 178, 130, fill=LIGHT_BLUE, stroke=(0.78, 0.87, 0.91))
    c.text(408, 562, "PROJECT INVESTMENT", size=7.5, font="F2", color=MID_GRAY)
    c.text(408, 532, _money(total), size=22, font="F2", color=NAVY)
    c.text(408, 514, "Materials, labor, equipment, protection, and cleanup", size=7, color=MID_GRAY)
    c.line(408, 500, 554, 500, color=(0.72, 0.82, 0.86), width=0.7)
    c.text(408, 490, deposit_label, size=8, color=DARK)
    c.right_text(554, 490, _money(deposit), size=8.5, font="F2", color=NAVY)
    c.text(408, 474, "Balance after deposit", size=8, color=DARK)
    c.right_text(554, 474, _money(max(0, total - deposit)), size=8.5, font="F2", color=NAVY)
    if estimate.get("estimated_duration"):
        c.text(408, 458, "Estimated duration", size=7.2, color=DARK)
        c.right_text(554, 458, str(estimate.get("estimated_duration"))[:24], size=7.7, font="F2", color=NAVY)

    c.text(42, 430, "Scope at a glance", size=13, font="F2", color=NAVY)
    c.right_text(570, 430, "Detailed quantities and descriptions begin on page 2", size=7.2, color=MID_GRAY)
    y = 408
    for idx, group in enumerate(groups[:5], start=1):
        c.rect(42, y - 43, 528, 43, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
        c.rect(52, y - 32, 25, 24, fill=LIGHT_BLUE if idx % 3 == 1 else PALE_GREEN if idx % 3 == 2 else PALE_PINK)
        c.text(59, y - 24, f"{idx:02d}", size=7.5, font="F2", color=BLUE if idx % 3 == 1 else GREEN if idx % 3 == 2 else MAGENTA)
        c.text(89, y - 18, group.get("name") or "Scope", size=9, font="F2", color=NAVY)
        c.wrapped(89, y - 31, group.get("description") or ", ".join(str(line.get("name")) for line in (group.get("lines") or [])[:2]), width=350, size=6.7, leading=8, color=MID_GRAY, max_lines=1)
        c.right_text(560, y - 24, _money(group.get("subtotal_cents") or 0), size=9, font="F2", color=NAVY)
        y -= 43

    c.text(42, 160, "Simple next steps", size=13, font="F2", color=NAVY)
    next_steps = [
        ("1", "Review", "Confirm the recommended scope and any optional upgrades."),
        ("2", "Authorize", "Sign the secure Floodman Work Authorization sent to your email."),
        ("3", "Deposit", "Pay the requested deposit through the secure Floodman payment page."),
        ("4", "Schedule", "Floodman confirms the project window and arrival details."),
    ]
    for i, (num, title, text) in enumerate(next_steps):
        x = 42 + i * 134
        c.rect(x, 72, 126, 72, fill=LIGHT_GRAY, stroke=(0.82, 0.86, 0.89), width=0.5)
        c.rect(x + 8, 122, 16, 16, fill=NAVY)
        c.text(x + 13, 127, num, size=6.5, font="F2", color=WHITE)
        c.text(x + 8, 107, title, size=8, font="F2", color=NAVY)
        c.wrapped(x + 8, 94, text, width=110, size=6.5, leading=8, color=MID_GRAY, max_lines=3)
    _footer(c, number, 1, "__TOTAL_PAGES__")

    # Page 2, with automatic overflow pages if needed.
    c.new_page()
    _brand_header(c, "PROJECT ESTIMATE", number, "READY FOR REVIEW")
    c.text(42, 658, "DETAILED SCOPE OF WORK", size=8, font="F2", color=MID_GRAY)
    c.text(42, 640, "Included services, materials, and quantities", size=13, font="F2", color=NAVY)
    c.right_text(570, 640, "Customer pricing only. Internal costs remain private.", size=7, color=MID_GRAY)
    page_no, y = _section_rows(c, groups, start_y=612, end_y=102, page_number=2, total_pages="__TOTAL_PAGES__", number=number)
    c.rect(360, 54, 210, 58, fill=WHITE, stroke=(0.72, 0.78, 0.82), width=0.6)
    c.text(372, 94, "Project subtotal", size=8, color=DARK)
    c.right_text(558, 94, _money(total), size=9, font="F2", color=NAVY)
    c.rect(360, 54, 210, 25, fill=NAVY)
    c.text(372, 62, "TOTAL PROJECT INVESTMENT", size=8.5, font="F2", color=WHITE)
    c.right_text(558, 62, _money(total), size=10, font="F2", color=WHITE)
    _footer(c, number, page_no, "__TOTAL_PAGES__")

    # RoomFlow plan page follows however many detailed-scope pages were required.
    plan_page = page_no + 1
    c.new_page()
    _brand_header(c, "PROJECT ESTIMATE", number, "READY FOR REVIEW")
    c.text(42, 658, "ROOMFLOW PROJECT PLAN", size=8, font="F2", color=MID_GRAY)
    c.text(42, 640, "Measured work areas and installation points", size=13, font="F2", color=NAVY)
    c.right_text(570, 640, "Generated from the saved property sketch", size=7, color=MID_GRAY)
    c.rect(42, 370, 528, 250, fill=(0.985, 0.990, 0.995), stroke=(0.80, 0.84, 0.88), width=0.8)
    roomflow_job = estimate.get("roomflow_job") if isinstance(estimate.get("roomflow_job"), dict) else {}
    roomflow_label = str(roomflow_job.get("job_name") or property_record.get("name") or property_record.get("property_name") or "Service Property")
    c.text(54, 602, roomflow_label + " - Measured Work Plan", size=9, font="F2", color=NAVY)
    layout_source = estimate.get("roomflow_layout_path") or roomflow_job.get("layout_path")
    if c.image(54, 398, 504, 188, layout_source, fit="contain"):
        c.text(54, 384, "Actual saved RoomFlow layout. Measurements and markers remain subject to field verification.", size=7, color=MID_GRAY)
    else:
        c.rect(78, 430, 456, 118, fill=WHITE, stroke=(0.75, 0.80, 0.84), width=0.8)
        c.text(130, 505, "NO SAVED ROOMFLOW LAYOUT ATTACHED", size=12, font="F2", color=NAVY)
        c.wrapped(112, 478, "Open the linked RoomFlow job, save the measured layout, and resync the estimate. Floodman will not manufacture a placeholder drawing.", width=390, size=8.5, leading=11, color=MID_GRAY, max_lines=4)
        summary = roomflow_job.get("summary") if isinstance(roomflow_job.get("summary"), dict) else {}
        if summary:
            c.text(112, 438, f"Saved RoomFlow record: {summary.get('rooms', 0)} rooms, {summary.get('levels', 0)} levels, {summary.get('measurements', 0)} measurements", size=7.5, color=MID_GRAY)
        c.text(54, 384, "No layout image was present in the saved RoomFlow job.", size=7, color=MID_GRAY)

    def detail_rows(value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, list):
            rows = [str(item).strip() for item in value if str(item).strip()]
        else:
            rows = [row.strip(" -•\t") for row in str(value or "").splitlines() if row.strip(" -•\t")]
        return (rows or fallback)[:4]

    boxes = [
        (42, 235, "PROJECT ASSUMPTIONS", detail_rows(estimate.get("assumptions"), ["Accessible conditions observed during inspection", "Normal access to utilities and work areas", "Quantities may be field-verified before installation"])),
        (310, 235, "NOT INCLUDED UNLESS LISTED", detail_rows(estimate.get("exclusions"), ["Concealed conditions not visible at inspection", "Finish work beyond the listed restoration", "Hazardous-material work outside the documented scope"])),
        (42, 105, "INCLUDED PROJECT PROTECTIONS", detail_rows(estimate.get("project_protections") or plan.get("protections"), ["Controlled work area and protected access", "Daily housekeeping in the active work zone", "Debris removal and final photo documentation"])),
        (310, 105, "AVAILABLE OPTIONS, NOT INCLUDED", detail_rows(estimate.get("project_options") or plan.get("options"), ["Questions and scheduling details remain linked to the Floodman customer and property file"])),
    ]
    for x, yb, title, rows in boxes:
        c.rect(x, yb, 260, 115, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
        c.text(x + 10, yb + 94, title, size=7.5, font="F2", color=MID_GRAY)
        cursor = yb + 74
        for row in rows:
            c.text(x + 12, cursor, "- " + row, size=7.2, color=DARK)
            cursor -= 19
    _footer(c, number, plan_page, "__TOTAL_PAGES__")

    # Approval page
    approval_page = plan_page + 1
    c.new_page()
    _brand_header(c, "PROJECT ESTIMATE", number, "READY FOR REVIEW")
    c.text(42, 658, "APPROVAL AND PAYMENT", size=8, font="F2", color=MID_GRAY)
    c.text(42, 640, "A clear path from estimate to scheduled work", size=13, font="F2", color=NAVY)
    _info_box(c, 42, 548, 160, 72, "Total project", [_money(total), "Approved scope shown in this estimate"])
    _info_box(c, 210, 548, 160, 72, "Deposit requested", [_money(deposit), "Due " + ("after authorization" if str(estimate.get("deposit_due_stage") or "AFTER_AUTHORIZATION").upper() == "AFTER_AUTHORIZATION" else "when estimate is sent")])
    _info_box(c, 378, 548, 192, 72, "Remaining balance", [_money(max(0, total - deposit)), "Normally due at completion"])
    c.rect(42, 350, 528, 176, fill=LIGHT_BLUE, stroke=(0.75, 0.86, 0.91), width=0.8)
    c.text(58, 500, "APPROVAL PATH", size=7.5, font="F2", color=MID_GRAY)
    c.text(58, 474, "Ready to protect your property?", size=16, font="F2", color=NAVY)
    c.wrapped(58, 450, "Floodman sends a secure Work Authorization for electronic signature. After it is signed, the requested deposit reserves the project for scheduling.", width=470, size=9, leading=12, color=DARK, max_lines=4)
    c.text(58, 392, f"Total project  {_money(total)}", size=9, font="F2", color=NAVY)
    c.text(58, 374, f"Deposit requested  {_money(deposit)}", size=9, font="F2", color=NAVY)
    c.text(278, 392, f"Deposit paid  {_money(deposit_paid)}", size=9, font="F2", color=NAVY)
    c.text(278, 374, f"Deposit due  {_money(deposit_due)}", size=9, font="F2", color=NAVY)
    if public_url:
        c.rect(412, 372, 142, 32, fill=BLUE)
        c.text(429, 383, "OPEN FLOODMAN PAYMENT", size=7.4, font="F2", color=WHITE)
        c.link(412, 372, 142, 32, public_url)
        c.wrapped(58, 335, f"Secure estimate and payment link: {public_url}", width=490, size=7, leading=9, color=MID_GRAY, max_lines=2)
        c.link(54, 316, 500, 30, public_url)
    c.text(42, 316, "What approval records", size=13, font="F2", color=NAVY)
    c.rect(42, 170, 250, 126, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
    c.text(54, 278, "BEFORE WORK BEGINS", size=7.5, font="F2", color=MID_GRAY)
    before = ["Estimate number and revision", "Customer and service property", "Approved scope and deposit terms", "Electronic signature and audit record"]
    for i, row in enumerate(before):
        c.text(56, 254 - i * 20, "- " + row, size=7.5, color=DARK)
    c.rect(310, 170, 260, 126, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
    c.text(322, 278, "AFTER APPROVAL", size=7.5, font="F2", color=MID_GRAY)
    after = ["Signed authorization stored with the project", "Deposit added to the Floodman payment ledger", "Later changes require a signed change order", "Completion and warranty records remain attached"]
    for i, row in enumerate(after):
        c.text(324, 254 - i * 20, "- " + row, size=7.5, color=DARK)
    c.rect(42, 90, 528, 60, fill=PALE_GREEN)
    c.wrapped(54, 130, "Your total does not change casually. A revised price appears only through a clearly described and approved revision or Change Order.", width=500, size=8, leading=10, font="F2", color=NAVY, max_lines=3)
    _footer(c, number, approval_page, "__TOTAL_PAGES__")
    _finalize_page_count(c)
    return c.build()


def build_invoice_pdf(invoice: dict[str, Any], contact: dict[str, Any], property_record: dict[str, Any], profile: dict[str, Any], *, payments: list[dict[str, Any]] | None = None, documents: list[dict[str, Any]] | None = None, public_url: str = "") -> bytes:
    c = PdfCanvas()
    payments = sorted(list(payments or []), key=lambda item: str(item.get("payment_date") or item.get("created_at") or ""))
    documents = list(documents or [])
    groups = group_document_lines(invoice)
    number = str(invoice.get("invoice_number") or invoice.get("id") or "INVOICE")
    total = int(invoice.get("total_cents") or 0)
    paid = int(invoice.get("paid_cents") or sum(int(p.get("amount_cents") or 0) for p in payments))
    balance = max(0, int(invoice.get("balance_cents") if invoice.get("balance_cents") is not None else total - paid))
    status = "PAID" if balance == 0 else "BALANCE DUE"
    _brand_header(c, "INVOICE", number, status)

    c.rect(42, 550, 290, 112, fill=NAVY)
    c.text(58, 638, "AMOUNT DUE NOW", size=7.5, font="F2", color=(0.65, 0.82, 0.90))
    c.text(58, 596, _money(balance), size=27, font="F2", color=WHITE)
    c.wrapped(58, 574, "Final balance for the approved Floodman project. Due upon receipt.", width=250, size=8.5, leading=11, color=WHITE, max_lines=3)
    _info_box(c, 344, 604, 108, 58, "Issue date", [_date(invoice.get("issued_at") or invoice.get("created_at"), _date(datetime.now(UTC)))])
    _info_box(c, 462, 604, 108, 58, "Due date", ["Due upon receipt"])
    _info_box(c, 344, 550, 108, 46, "Service completed", [_date(invoice.get("service_completed_at") or invoice.get("issued_at"), "On file")])
    _info_box(c, 462, 550, 108, 46, "Payment terms", [str(invoice.get("payment_terms") or "Due upon receipt")])

    _info_box(c, 42, 470, 160, 66, "Bill to", [_contact_name(contact), _contact_email(contact), _contact_phone(contact)])
    _info_box(c, 210, 470, 200, 66, "Service property", _property_lines(property_record)[:3])
    _info_box(c, 418, 470, 152, 66, "Project reference", [str(invoice.get("estimate_number") or invoice.get("estimate_id") or "Floodman project"), str(invoice.get("roomflow_job_id") or "Project file"), f"Prepared by {invoice.get('prepared_by') or 'Josh Aldrich'}"])

    estimate_total = int(invoice.get("approved_estimate_cents") or total)
    changes = int(invoice.get("approved_change_orders_cents") or max(0, total - estimate_total))
    _info_box(c, 42, 405, 160, 50, "Approved estimate", [_money(estimate_total)])
    _info_box(c, 210, 405, 160, 50, "Approved change orders", [_money(changes)])
    _info_box(c, 378, 405, 192, 50, "Revised contract total", [_money(total)])

    c.text(42, 380, "Invoice details", size=13, font="F2", color=NAVY)
    y = 356
    # Condensed group summary for page 1.
    for group in groups[:5]:
        c.rect(42, y - 42, 528, 42, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.5)
        c.text(52, y - 16, group.get("name") or "Approved project scope", size=8.5, font="F2", color=NAVY)
        c.wrapped(52, y - 28, ", ".join(str(line.get("name")) for line in (group.get("lines") or [])[:3]), width=390, size=6.6, leading=8, color=MID_GRAY, max_lines=1)
        c.right_text(560, y - 19, _money(group.get("subtotal_cents") or 0), size=8.5, font="F2", color=NAVY)
        y -= 42
        if y < 205:
            break

    c.rect(350, 122, 220, 76, fill=WHITE, stroke=(0.75, 0.80, 0.84), width=0.7)
    c.text(364, 176, "Revised contract total", size=8, color=DARK)
    c.right_text(558, 176, _money(total), size=8.5, font="F2", color=NAVY)
    c.text(364, 156, "Payments received", size=8, color=DARK)
    c.right_text(558, 156, _money(-paid), size=8.5, font="F2", color=NAVY)
    c.rect(350, 122, 220, 26, fill=NAVY)
    c.text(364, 131, "Balance due", size=10, font="F2", color=WHITE)
    c.right_text(558, 131, _money(balance), size=10, font="F2", color=WHITE)

    c.text(42, 176, "Secure payment", size=13, font="F2", color=NAVY)
    c.rect(42, 90, 292, 70, fill=LIGHT_BLUE, stroke=(0.76, 0.87, 0.92), width=0.6)
    if balance:
        c.text(54, 138, "Pay securely through Floodman", size=9.5, font="F2", color=NAVY)
        c.wrapped(54, 122, "Use the secure Floodman payment page below. Payment status and remaining balance update against this same Floodman invoice.", width=260, size=6.8, leading=8.5, color=MID_GRAY, max_lines=3)
        if public_url:
            c.wrapped(54, 99, public_url, width=260, size=6.4, leading=7.5, font="F2", color=BLUE, max_lines=2)
            c.link(42, 90, 292, 70, public_url)
    else:
        c.text(54, 135, "PAID IN FULL", size=13, font="F2", color=GREEN)
        c.text(54, 116, "This document is the customer receipt.", size=8, color=MID_GRAY)
    _footer(c, number, 1, "__TOTAL_PAGES__")

    # Page 2
    c.new_page()
    _brand_header(c, "INVOICE", number, status)
    c.text(42, 658, "ACCOUNT ACTIVITY", size=8, font="F2", color=MID_GRAY)
    c.text(42, 640, "Payment and balance history", size=13, font="F2", color=NAVY)
    c.rect(42, 610, 528, 24, fill=LIGHT_GRAY, stroke=(0.82, 0.86, 0.89), width=0.5)
    for x, label in ((52, "DATE"), (145, "ACTIVITY"), (405, "REFERENCE"), (515, "AMOUNT")):
        c.text(x, 619, label, size=7, font="F2", color=MID_GRAY)
    y = 610
    for payment in payments[-8:]:
        y -= 27
        c.rect(42, y, 528, 27, fill=WHITE, stroke=(0.86, 0.88, 0.90), width=0.4)
        c.text(52, y + 9, _date(payment.get("payment_date") or payment.get("created_at")), size=7.2, color=DARK)
        method = str(payment.get("method") or "Payment").replace("_", " ").title()
        c.text(145, y + 9, method, size=7.2, color=DARK)
        c.text(405, y + 9, str(payment.get("reference") or payment.get("processor_payment_id") or "Floodman receipt")[:20], size=6.8, color=MID_GRAY)
        c.right_text(558, y + 9, _money(-int(payment.get("amount_cents") or 0)), size=7.5, font="F2", color=NAVY)
    y -= 30
    c.rect(42, y, 528, 25, fill=PALE_PINK if balance else PALE_GREEN)
    c.text(145, y + 8, "Current balance due" if balance else "Paid in full", size=8, font="F2", color=NAVY)
    c.right_text(558, y + 8, _money(balance), size=8.5, font="F2", color=MAGENTA if balance else GREEN)

    c.text(42, y - 35, "Completion record", size=13, font="F2", color=NAVY)
    box_y = y - 175
    c.rect(42, box_y, 255, 125, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
    c.text(54, box_y + 104, "WORK COMPLETED", size=7.5, font="F2", color=MID_GRAY)
    completion = invoice.get("completion_items") if isinstance(invoice.get("completion_items"), list) else [
        "Approved project scope completed",
        "Final cleanup and project documentation recorded",
        "Customer file updated with payment and completion history",
    ]
    for i, row in enumerate(completion[:4]):
        c.text(56, box_y + 80 - i * 21, "- " + str(row), size=7.2, color=DARK)
    c.rect(315, box_y, 255, 125, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
    c.text(327, box_y + 104, "SIGNED DOCUMENTS", size=7.5, font="F2", color=MID_GRAY)
    signed = [doc for doc in documents if str(doc.get("status") or "").upper() in {"SIGNED", "COMPLETED", "EXECUTED"}]
    if not signed:
        signed_rows = ["Work Authorization and completion records remain attached to the customer file"]
    else:
        signed_rows = [f"{doc.get('document_type') or doc.get('title')}: signed {_date(doc.get('completed_at') or doc.get('signed_at'))}" for doc in signed[:4]]
    for i, row in enumerate(signed_rows):
        c.wrapped(329, box_y + 80 - i * 21, "- " + str(row), width=220, size=7.2, leading=8.5, color=DARK, max_lines=2)

    c.text(42, box_y - 36, "What happens after payment", size=13, font="F2", color=NAVY)
    steps = [
        ("1", "Payment posts", "Floodman confirms the transaction and updates the balance."),
        ("2", "Receipt sends", "A paid receipt is emailed and stored with the project."),
        ("3", "Status closes", "The invoice changes to Paid without creating a duplicate record."),
        ("4", "Records remain", "Estimate, signatures, photos, payments, and warranty stay linked."),
    ]
    for i, (num, title, text) in enumerate(steps):
        x = 42 + i * 134
        c.rect(x, box_y - 126, 126, 78, fill=LIGHT_GRAY, stroke=(0.82, 0.86, 0.89), width=0.5)
        c.rect(x + 8, box_y - 69, 16, 16, fill=NAVY)
        c.text(x + 13, box_y - 64, num, size=6.5, font="F2", color=WHITE)
        c.text(x + 8, box_y - 87, title, size=7.8, font="F2", color=NAVY)
        c.wrapped(x + 8, box_y - 100, text, width=110, size=6.4, leading=7.8, color=MID_GRAY, max_lines=3)

    c.text(42, 128, "Project notes", size=13, font="F2", color=NAVY)
    c.rect(42, 68, 528, 45, fill=WHITE, stroke=(0.82, 0.86, 0.89), width=0.6)
    c.wrapped(54, 96, invoice.get("customer_notes") or "Thank you for trusting Floodman with your property. Contact our office with billing, project, or warranty questions.", width=500, size=7.2, leading=9, color=MID_GRAY, max_lines=3)
    _footer(c, number, 2, "__TOTAL_PAGES__")
    _finalize_page_count(c)
    return c.build()
