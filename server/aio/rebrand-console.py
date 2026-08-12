#!/usr/bin/env python3
"""Stream-filter upstream technical log labels into Floodman branding.

This changes console presentation only. It does not rewrite exception semantics,
paths on disk, database identifiers, or the separate legal notices page.
"""
from __future__ import annotations

import re
import sys

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Ever\s+Gauzy", re.IGNORECASE), "Floodman Operations"),
    (re.compile(r"Ever\s+Technologies(?:\s+LTD)?", re.IGNORECASE), "Floodman"),
    (re.compile(r"Ever\s+Co\.?\s*(?:LTD)?", re.IGNORECASE), "Floodman"),
    (re.compile(r"gauzy\.co", re.IGNORECASE), "floodman.com"),
    (re.compile(r"example-ever\.co", re.IGNORECASE), "example.floodman.local"),
    (re.compile(r"@gauzy/", re.IGNORECASE), "@floodman/"),
    (re.compile(r"/srv/gauzy", re.IGNORECASE), "/srv/floodman-erp"),
    (re.compile(r"gauzy-api", re.IGNORECASE), "floodman-erp-api"),
    (re.compile(r"gauzy-webapp", re.IGNORECASE), "floodman-erp-web"),
    (re.compile(r"\bGauzy\b", re.IGNORECASE), "Floodman"),
    (re.compile(r"\bEver\b", re.IGNORECASE), "Floodman"),
)

for line in sys.stdin:
    rendered = line
    for pattern, replacement in PATTERNS:
        rendered = pattern.sub(replacement, rendered)
    sys.stdout.write(rendered)
    sys.stdout.flush()
