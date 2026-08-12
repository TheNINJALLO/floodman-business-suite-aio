from __future__ import annotations

import re


class InvalidPhone(ValueError):
    pass


def normalize_phone(value: str, default_country_code: str = "1") -> str:
    raw = (value or "").strip()
    if not raw:
        raise InvalidPhone("Phone number is empty")
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        if not 8 <= len(digits) <= 15:
            raise InvalidPhone("International phone number must contain 8 to 15 digits")
        return f"+{digits}"
    digits = re.sub(r"\D", "", raw)
    if default_country_code == "1":
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
    if not 8 <= len(digits) <= 15:
        raise InvalidPhone("Phone number must contain 8 to 15 digits")
    return f"+{default_country_code}{digits}"


def mask_phone(value: str) -> str:
    try:
        normalized = normalize_phone(value)
    except InvalidPhone:
        return "unknown"
    return f"***-***-{normalized[-4:]}"


def normalize_e164(value: str, default_country: str = "US") -> str | None:
    """Return E.164 or None when a customer phone cannot be normalized safely."""
    country_code = "1" if default_country.upper() in {"US", "USA", "CA", "CAN"} else "1"
    try:
        return normalize_phone(value, country_code)
    except InvalidPhone:
        return None
