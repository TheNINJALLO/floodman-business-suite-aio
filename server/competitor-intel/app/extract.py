from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any


class Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.headings: list[str] = []
        self.links: list[dict[str, str]] = []
        self.text: list[str] = []
        self._tag = ""
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag = tag
        values = {k.lower(): v or "" for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        if tag == "meta":
            key = values.get("name") or values.get("property")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"].strip()
        if tag == "a" and values.get("href"):
            self.links.append({"href": values["href"], "text": ""})

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        self._tag = ""

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._hidden:
            return
        if self._tag == "title":
            self.title = (self.title + " " + value).strip()
        if self._tag in {"h1", "h2", "h3"}:
            self.headings.append(value)
        if self._tag == "a" and self.links:
            self.links[-1]["text"] = (self.links[-1]["text"] + " " + value).strip()
        self.text.append(value)


PRICE_RE = re.compile(r"(?<!\w)\$\s?\d[\d,]*(?:\.\d{2})?(?:\s*(?:/|per)\s*(?:month|year|job|visit|sq\.?\s*ft))?", re.I)
PHONE_RE = re.compile(r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}")
SERVICE_TERMS = (
    "water damage", "flood cleanup", "basement waterproofing", "foundation repair",
    "mold remediation", "crawl space", "sump pump", "drainage", "emergency service",
    "free estimate", "financing", "lifetime warranty", "same day",
)


def extract_page(url: str, html: str, max_chars: int) -> dict[str, Any]:
    parser = Extractor()
    parser.feed(html)
    text = "\n".join(parser.text)
    compact = text[:max_chars]
    lower = compact.lower()
    return {
        "url": url,
        "title": parser.title[:500],
        "description": (parser.meta.get("description") or parser.meta.get("og:description") or "")[:2000],
        "headings": parser.headings[:100],
        "prices": sorted(set(PRICE_RE.findall(compact)))[:50],
        "phones": sorted(set(PHONE_RE.findall(compact)))[:20],
        "service_claims": [term for term in SERVICE_TERMS if term in lower],
        "important_links": [link for link in parser.links if any(k in link["text"].lower() for k in ("service", "price", "review", "about", "contact", "financing"))][:80],
        "text": compact,
        "sha256": hashlib.sha256(html.encode(errors="replace")).hexdigest(),
    }
