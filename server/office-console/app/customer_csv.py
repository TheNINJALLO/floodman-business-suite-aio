from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Iterable

from email_validator import EmailNotValidError, validate_email


MAX_CUSTOMER_ROWS = 100_000
MAX_CUSTOMER_CSV_BYTES = 50 * 1024 * 1024
MATTER_EXPORT_PROFILE = "MATTER_CLIENT_EXPORT_V1"


class CustomerCsvError(ValueError):
    pass


# Every field in the currently supplied Floodman client export is either mapped
# into an operational field or retained as source metadata. Nothing disappears
# merely because it is not a standard ERP contact column.
HEADER_ALIASES: dict[str, set[str]] = {
    "external_id": {
        "customerid", "contactid", "clientid", "accountid", "id", "customernumber", "accountnumber",
        "legacycustomerid", "legacycontactid", "recordid",
    },
    "first_name": {"firstname", "first", "givenname", "customerfirstname", "contactfirstname"},
    "last_name": {"lastname", "last", "surname", "familyname", "customerlastname", "contactlastname"},
    "full_name": {"name", "fullname", "customername", "clientname", "contactname", "displayname"},
    "company": {"company", "business", "businessname", "organization", "organisation", "companyname"},
    "email": {"email", "emailaddress", "primaryemail", "customeremail", "contactemail"},
    "email_secondary": {"email2", "secondaryemail", "alternateemail", "alternativeemail", "otheremail"},
    "phone": {
        "phone", "phonenumber", "primaryphone", "mobile", "mobilephone", "mobilenumber", "cell", "cellphone",
        "telephone", "customerphone", "contactphone", "homephone", "workphone",
    },
    "mailing_address": {
        "address", "address1", "street", "streetaddress", "billingaddress", "mailingaddress", "addressline1",
        "customeraddress", "primaryaddress",
    },
    "mailing_address2": {"address2", "addressline2", "suite", "unit", "apartment", "mailingaddress2"},
    "city": {"city", "town", "billingcity", "mailingcity"},
    "state": {"state", "province", "region", "billingstate", "mailingstate"},
    "postal_code": {"zip", "zipcode", "postalcode", "postcode", "billingzip", "mailingzip"},
    "country": {"country", "countrycode", "countryname"},
    "notes": {"notes", "note", "comments", "comment", "customernotes", "description"},
    "lead_source": {"leadsource", "source", "referral", "howheard", "marketingsource"},
    "created_at": {"createdat", "createddate", "datecreated", "customercreated", "addeddate"},
    "property_address": {"propertyaddress", "serviceaddress", "jobaddress", "projectaddress", "siteaddress"},
    "property_type": {"propertytype", "servicetype", "buildingtype"},
    "property_name": {"propertyname", "locationname", "sitename", "jobsite", "serviceproperty"},
    "help_request": {"howcanwehelpyou", "howcanwehelp", "servicerequest", "request", "inquiry"},
    "special_instructions": {"specialinstructionsrequests", "specialinstructions", "specialrequests"},
    "time_zone": {"timezone", "timezonename"},
    "preferred_language": {"preferredlanguage", "language"},
    "source_channel": {"sourcechannel", "channel"},
    "source_campaign": {"sourcecampaign", "campaign"},
    "source_url": {"sourceurl", "landingpage", "referrerurl"},
    "unsubscribed": {"unsubscribed", "emailunsubscribed"},
    "email_blocked": {"emailblocked", "blockedemail"},
    "tags": {"tags", "tag"},
    "last_activity_at": {"lastactivitytime", "lastactivityat", "lastactivitydate"},
    "assigned_staff": {"assignedstaff", "assignedto", "owner", "staff"},
    "review_score": {"reviewscore", "rating"},
    "next_booking": {"nextbooking", "nextappointment", "appointmentdate"},
    "last_activity_action": {"lastactivityaction", "lastaction"},
    "transactional_opt_in": {"optedinfortransactional", "transactionaloptin"},
    "pending_estimates_total": {"pendingestimatestotal", "pendingestimates"},
    "open_payments_total": {"openpayments", "openpaymentstotal", "outstandingpayments"},
    "approved_estimates_total": {"approvedestimatestotal", "approvedestimates"},
    "status": {"status", "customerstatus", "contactstatus"},
    "birthday": {"birthday", "dateofbirth", "dob"},
    "promotional_opt_in": {"idliketoreceivepromotionalupdates", "promotionaloptin", "marketingoptin"},
    "referred_by": {"referredby", "referrer", "referralname"},
}

MATTER_REQUIRED_NORMALIZED_HEADERS = {
    "firstname", "lastname", "email", "countryname", "address", "notes", "timezone", "preferredlanguage",
    "source", "sourcechannel", "createdat", "unsubscribed", "emailblocked", "tags", "assignedstaff",
    "optedinfortransactional", "pendingestimatestotal", "openpayments", "approvedestimatestotal", "status",
    "idliketoreceivepromotionalupdates", "propertyaddress", "propertytype", "howcanwehelpyou",
    "specialinstructionsrequests", "propertyname", "mobilephone",
}

STATUS_MAP = {
    "existing customer": "ACTIVE_CUSTOMER",
    "potential customer": "LEAD",
    "lapsed customer": "LAPSED_CUSTOMER",
    "vendor": "VENDOR",
    "staff": "STAFF",
    "closed": "CLOSED",
}

COUNTRY_VALUES = {"us": "US", "usa": "US", "unitedstates": "US", "unitedstatesofamerica": "US"}
STATE_VALUES = {"mi": "MI", "michigan": "MI"}
STREET_SUFFIXES = {
    "alley", "ave", "avenue", "blvd", "boulevard", "circle", "cir", "court", "ct", "drive", "dr", "highway",
    "hwy", "lane", "ln", "loop", "parkway", "pkwy", "place", "pl", "road", "rd", "route", "street", "st",
    "trail", "trl", "terrace", "way", "crossing", "point", "pointe",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _plain(value: Any, *, keep_lines: bool = False) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Cf")
    parser = _TextExtractor()
    try:
        parser.feed(unescape(raw))
        text = "".join(parser.parts)
    except Exception:
        text = unescape(re.sub(r"<[^>]+>", " ", raw))
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    if keep_lines:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        return "\n".join(line for line in lines if line)
    return re.sub(r"\s+", " ", text).strip()


def _decode(data: bytes) -> tuple[str, str]:
    # UTF-16 is common for exports opened and resaved by Excel on Windows.
    encodings = ("utf-8-sig", "utf-8", "utf-16", "cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CustomerCsvError("The customer CSV must be UTF-8, UTF-16, or Windows-1252 encoded.")


def _dialect(text: str) -> csv.Dialect:
    sample = text[:64_000]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _detect_profile(headers: list[str]) -> str:
    normalized = {normalize_header(value) for value in headers}
    if MATTER_REQUIRED_NORMALIZED_HEADERS.issubset(normalized):
        return MATTER_EXPORT_PROFILE
    return "GENERIC_CUSTOMER_CSV"


def _header_mapping(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    normalized = {header: normalize_header(header) for header in headers if str(header or "").strip()}
    mapped: dict[str, str] = {}
    used: set[str] = set()
    for canonical, aliases in HEADER_ALIASES.items():
        for header, key in normalized.items():
            if header in used:
                continue
            if key in aliases:
                mapped[canonical] = header
                used.add(header)
                break

    fallbacks = {
        "email": ("email",),
        "email_secondary": ("email2", "secondaryemail"),
        "phone": ("phone", "mobile", "cell"),
        "postal_code": ("zip", "postal"),
        "first_name": ("firstname",),
        "last_name": ("lastname",),
        "full_name": ("customername", "contactname", "fullname"),
        "mailing_address": ("streetaddress", "mailingaddress", "billingaddress"),
        "property_address": ("propertyaddress", "serviceaddress", "jobaddress"),
    }
    for canonical, needles in fallbacks.items():
        if canonical in mapped:
            continue
        for header, key in normalized.items():
            if header in used:
                continue
            if any(needle in key for needle in needles):
                mapped[canonical] = header
                used.add(header)
                break

    ignored = [header for header in headers if header not in used]
    return mapped, ignored


def _value(row: dict[str, str], mapping: dict[str, str], key: str, *, lines: bool = False) -> str:
    header = mapping.get(key)
    return _plain(row.get(header, "") if header else "", keep_lines=lines)


def _split_name(full_name: str) -> tuple[str, str]:
    value = re.sub(r"\s+", " ", full_name.strip())
    if not value:
        return "", ""
    if "," in value:
        last, first = [part.strip() for part in value.split(",", 1)]
        return first, last
    parts = value.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def _phone_parts(value: str) -> tuple[str, str, str]:
    raw = _plain(value)
    if not raw:
        return "", "", ""
    # Prefer a phone-like group rather than combining unrelated digits in notes.
    matches = re.findall(r"(?:\+?\d[\d\s().\-]{6,}\d)", raw)
    candidate = matches[0] if matches else raw.split("/", 1)[0]
    digits = re.sub(r"\D", "", candidate)
    normalized = ""
    key = ""
    if len(digits) == 11 and digits.startswith("1"):
        normalized, key = "+" + digits, digits[1:]
    elif len(digits) == 10:
        normalized, key = "+1" + digits, digits
    elif 8 <= len(digits) <= 15:
        normalized, key = "+" + digits, digits
    elif digits:
        key = digits
    return raw, normalized, key


def _text_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _email(value: str) -> tuple[str, str | None]:
    raw = _plain(value)
    if not raw:
        return "", None
    try:
        return validate_email(raw, check_deliverability=False).normalized, None
    except EmailNotValidError as exc:
        # Preserve the row and raw value. One malformed email should not hold
        # 1,999 valid customers hostage.
        return "", f"Invalid email {raw!r}: {exc}"


def _bool(value: str) -> bool | None:
    normalized = _plain(value).lower()
    if normalized in {"true", "1", "yes", "y", "on", "checked"}:
        return True
    if normalized in {"false", "0", "no", "n", "off", "unchecked"}:
        return False
    return None


def _money_cents(value: str) -> int:
    raw = _plain(value)
    if not raw:
        return 0
    negative = raw.startswith("(") and raw.endswith(")")
    number = re.sub(r"[^0-9.\-]", "", raw)
    if not number or number in {"-", ".", "-."}:
        return 0
    try:
        cents = round(float(number) * 100)
    except ValueError:
        return 0
    return -abs(cents) if negative else cents


def _iso_datetime(value: str) -> str:
    raw = _plain(value)
    if not raw:
        return ""
    formats = (
        "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            return parsed.isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except ValueError:
        return raw


def _tags(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[|,;]+", _plain(value)):
        tag = item.strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def _split_address_parts(value: str) -> list[str]:
    raw = _plain(value)
    if not raw:
        return []
    # Matter exports structured addresses with two or more spaces. Keep normal
    # single spaces inside street and city names.
    parts = [re.sub(r"\s+", " ", part).strip(" ,") for part in re.split(r"\s{2,}|\s*\|\s*", raw)]
    return [part for part in parts if part]


def _looks_like_street(value: str) -> bool:
    tokens = re.findall(r"[a-z]+", value.lower())
    return bool(re.search(r"\d", value)) or bool(tokens and tokens[-1] in STREET_SUFFIXES)


def _discover_localities(values: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for value in values:
        parts = _split_address_parts(value)
        if len(parts) < 3:
            continue
        trimmed = list(parts)
        if normalize_header(trimmed[-1]) in COUNTRY_VALUES:
            trimmed.pop()
        state_index = None
        for index in range(len(trimmed) - 1, -1, -1):
            token = normalize_header(re.sub(r"\b\d{5}(?:-\d{4})?\b", "", trimmed[index]))
            if token in STATE_VALUES:
                state_index = index
                break
        if state_index is None or state_index < 2:
            continue
        for part in trimmed[1:state_index]:
            if part and not re.search(r"\d", part) and len(part) <= 60:
                found.add(part)
    return sorted(found, key=lambda item: (-len(item), item.lower()))


def _extract_state_zip(value: str) -> tuple[str, str, str]:
    text = _plain(value)
    match = re.match(r"^(.*?)(?:\s+|,)(MI|Michigan)(?:\s*[-,]?\s*(\d{5}(?:-\d{4})?))?$", text, flags=re.I)
    if match:
        return match.group(1).strip(" ,"), "MI", match.group(3) or ""
    match = re.match(r"^(.*?)(?:\s+|,)(\d{5}(?:-\d{4})?)$", text)
    if match:
        return match.group(1).strip(" ,"), "", match.group(2)
    return text, "", ""


def _parse_single_address(value: str, localities: list[str]) -> dict[str, str]:
    text = _plain(value)
    working = re.sub(r"(?:,?\s+)(?:USA|US|United States(?: of America)?)$", "", text, flags=re.I).strip(" ,")
    base, state, postal = _extract_state_zip(working)
    city = ""
    street = base
    lowered = base.lower()
    for locality in localities:
        marker = " " + locality.lower()
        if lowered.endswith(marker):
            possible_street = base[: -len(marker)].strip(" ,")
            if possible_street:
                street, city = possible_street, locality
                break
    return {
        "raw": text,
        "street": street,
        "street2": "",
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": "US",
        "locality_extra": "",
        "label": "",
        "parse_confidence": "MEDIUM" if city or state or postal else "LOW",
    }


def _parse_address(value: str, localities: list[str], default_country: str = "US") -> dict[str, str]:
    raw = _plain(value)
    empty = {
        "raw": "", "street": "", "street2": "", "city": "", "state": "", "postal_code": "",
        "country": default_country or "US", "locality_extra": "", "label": "", "parse_confidence": "NONE",
    }
    if not raw:
        return empty

    parts = _split_address_parts(raw)
    if len(parts) <= 1:
        parsed = _parse_single_address(raw, localities)
        parsed["country"] = default_country or parsed["country"] or "US"
        return parsed

    country = default_country or "US"
    if normalize_header(parts[-1]) in COUNTRY_VALUES:
        country = COUNTRY_VALUES[normalize_header(parts[-1])]
        parts.pop()

    postal = ""
    state = ""
    state_index: int | None = None
    for index in range(len(parts) - 1, -1, -1):
        base, found_state, found_postal = _extract_state_zip("x " + parts[index])
        if found_state or found_postal:
            state = found_state
            postal = found_postal
            state_index = index
            break
        normalized = normalize_header(parts[index])
        if normalized in STATE_VALUES:
            state = STATE_VALUES[normalized]
            state_index = index
            break
        if re.fullmatch(r"\d{5}(?:-\d{4})?", parts[index]):
            postal = parts[index]
            parts.pop(index)
            continue

    if state_index is not None:
        state_part = parts.pop(state_index)
        if not postal:
            postal_match = re.search(r"\b\d{5}(?:-\d{4})?\b", state_part)
            if postal_match:
                postal = postal_match.group(0)

    if len(parts) == 1:
        parsed = _parse_single_address(" ".join([parts[0], state, postal]).strip(), localities)
        parsed["raw"] = raw
        parsed["country"] = country
        return parsed

    label = ""
    street = parts[0]
    city = parts[1] if len(parts) > 1 else ""
    extra = parts[2:] if len(parts) > 2 else []
    if len(parts) >= 3 and not _looks_like_street(parts[0]) and _looks_like_street(parts[1]):
        label, street, city, extra = parts[0], parts[1], parts[2], parts[3:]

    return {
        "raw": raw,
        "street": street,
        "street2": "",
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": country,
        "locality_extra": ", ".join(extra),
        "label": label,
        "parse_confidence": "HIGH" if street and city and state else "MEDIUM",
    }


def _row_contact_key(record: dict[str, Any]) -> str:
    if record.get("external_id"):
        return "external:" + _text_key(str(record["external_id"]))
    if record.get("email"):
        return "email:" + str(record["email"]).lower()
    phone_key = str(record.get("phone_key") or "")
    if len(phone_key) >= 10:
        return "phone:" + phone_key
    address = str((record.get("mailing_address") or {}).get("raw") or (record.get("service_address") or {}).get("raw") or "")
    return "name-address:" + _text_key(str(record.get("name") or "") + "|" + address)


def _fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _latest_key(record: dict[str, Any]) -> str:
    return str(record.get("last_activity_at") or record.get("created_at") or "")


def _first(values: Iterable[Any]) -> Any:
    for value in values:
        if value is None or value == "" or value == [] or value == {}:
            continue
        return value
    return ""


def _merge_notes(records: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for record in records:
        for value in (record.get("notes"), record.get("help_request"), record.get("special_instructions")):
            text = _plain(value, keep_lines=True)
            key = _text_key(text)
            if text and key and key not in seen:
                seen.add(key)
                parts.append(text)
    return "\n\n".join(parts)


def _merge_contact(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    newest = sorted(records, key=_latest_key, reverse=True)
    primary = newest[0]
    tags: list[str] = []
    seen_tags: set[str] = set()
    for record in newest:
        for tag in record.get("tags") or []:
            if tag.lower() not in seen_tags:
                seen_tags.add(tag.lower())
                tags.append(tag)

    properties: list[dict[str, Any]] = []
    seen_properties: set[str] = set()
    for record in records:
        address = record.get("service_address") or {}
        raw_address = str(address.get("raw") or "")
        # The supplied export fills Property name with the contact name on
        # nearly every row. Do not create an empty pseudo-property from that
        # label alone; a service address is required. Property-specific request
        # text remains preserved on the contact notes when the address is blank.
        if not raw_address:
            continue
        property_name = str(record.get("property_name") or address.get("label") or raw_address or record.get("name") or "Property")
        property_key = _text_key(raw_address)
        if not property_key or property_key in seen_properties:
            continue
        seen_properties.add(property_key)
        properties.append({
            "name": property_name,
            "property_name": property_name,
            "property_type": str(record.get("property_type") or ""),
            "raw_address": raw_address,
            **address,
            "help_request": str(record.get("help_request") or ""),
            "special_instructions": str(record.get("special_instructions") or ""),
            "source_row": int(record.get("row_number") or 0),
        })

    status_values = [str(record.get("status") or "") for record in newest]
    source_status = _first(status_values)
    if any(value == "ACTIVE_CUSTOMER" for value in status_values):
        status = "ACTIVE_CUSTOMER"
    elif any(value == "LEAD" for value in status_values):
        status = "LEAD"
    else:
        status = source_status or "ACTIVE"

    secondary_emails: list[str] = []
    for record in newest:
        for value in (record.get("email_secondary"),):
            if value and value not in secondary_emails and value != primary.get("email"):
                secondary_emails.append(str(value))

    addresses = []
    seen_addresses: set[str] = set()
    for record in newest:
        raw = str((record.get("mailing_address") or {}).get("raw") or "")
        key_address = _text_key(raw)
        if raw and key_address not in seen_addresses:
            seen_addresses.add(key_address)
            addresses.append(record.get("mailing_address"))

    quality_flags: list[str] = []
    if not primary.get("email") and not primary.get("phone"):
        quality_flags.append("NO_EMAIL_OR_PHONE")
    if not addresses and not properties:
        quality_flags.append("NO_ADDRESS")
    if any(record.get("email_error") for record in records):
        quality_flags.append("EMAIL_NEEDS_REVIEW")
    if any(
        str((record.get("service_address") or {}).get("parse_confidence")) == "LOW"
        and bool((record.get("service_address") or {}).get("raw"))
        and not re.search(r"\d", str((record.get("service_address") or {}).get("raw") or ""))
        for record in records
    ):
        quality_flags.append("ADDRESS_NEEDS_REVIEW")

    return {
        "dedupe_key": key,
        "source_row_count": len(records),
        "source_rows": [int(record.get("row_number") or 0) for record in records],
        "external_id": _first(record.get("external_id") for record in newest),
        "first_name": _first(record.get("first_name") for record in newest),
        "last_name": _first(record.get("last_name") for record in newest),
        "name": _first(record.get("name") for record in newest),
        "company": _first(record.get("company") for record in newest),
        "email": _first(record.get("email") for record in newest),
        "email_raw": _first(record.get("email_raw") for record in newest),
        "secondary_emails": secondary_emails,
        "phone": _first(record.get("phone") for record in newest),
        "phone_normalized": _first(record.get("phone_normalized") for record in newest),
        "mailing_address": addresses[0] if addresses else {},
        "additional_mailing_addresses": addresses[1:],
        "properties": properties,
        "notes": _merge_notes(records),
        "lead_source": _first(record.get("lead_source") for record in newest),
        "source_channel": _first(record.get("source_channel") for record in newest),
        "source_campaign": _first(record.get("source_campaign") for record in newest),
        "source_url": _first(record.get("source_url") for record in newest),
        "created_at": _first(record.get("created_at") for record in reversed(newest)),
        "last_activity_at": _first(record.get("last_activity_at") for record in newest),
        "last_activity_action": _first(record.get("last_activity_action") for record in newest),
        "next_booking": _first(record.get("next_booking") for record in newest),
        "assigned_staff": _first(record.get("assigned_staff") for record in newest),
        "assigned_staff_history": list(dict.fromkeys(str(record.get("assigned_staff") or "") for record in newest if record.get("assigned_staff"))),
        "time_zone": _first(record.get("time_zone") for record in newest) or "America/Detroit",
        "preferred_language": _first(record.get("preferred_language") for record in newest) or "en",
        "review_score": _first(record.get("review_score") for record in newest),
        "birthday": _first(record.get("birthday") for record in newest),
        "referred_by": _first(record.get("referred_by") for record in newest),
        "tags": tags,
        "status": status,
        "source_status": _first(record.get("source_status") for record in newest),
        "unsubscribed": any(record.get("unsubscribed") is True for record in records),
        "email_blocked": any(record.get("email_blocked") is True for record in records),
        "transactional_opt_in": any(record.get("transactional_opt_in") is True for record in records),
        "promotional_opt_in": any(record.get("promotional_opt_in") is True for record in records),
        "pending_estimates_cents": max((int(record.get("pending_estimates_cents") or 0) for record in records), default=0),
        "open_payments_cents": max((int(record.get("open_payments_cents") or 0) for record in records), default=0),
        "approved_estimates_cents": max((int(record.get("approved_estimates_cents") or 0) for record in records), default=0),
        "quality_flags": quality_flags,
        "source_fingerprint": str(primary.get("source_fingerprint") or ""),
        "source_records": [
            {
                "row_number": int(record.get("row_number") or 0),
                "fields": dict(record.get("source_fields") or {}),
            }
            for record in records
        ],
    }


@dataclass(frozen=True)
class CustomerCsvResult:
    summary: dict[str, Any]
    normalized: dict[str, Any]


def parse_customer_csv(data: bytes, filename: str = "customers.csv") -> CustomerCsvResult:
    if not data:
        raise CustomerCsvError("The customer CSV is empty.")
    if len(data) > MAX_CUSTOMER_CSV_BYTES:
        raise CustomerCsvError("The customer CSV exceeds the 50 MB limit.")

    text, encoding = _decode(data)
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=_dialect(text))
    headers = [str(value or "").strip() for value in (reader.fieldnames or [])]
    if not headers:
        raise CustomerCsvError("The customer CSV does not contain a header row.")
    profile = _detect_profile(headers)
    mapping, ignored = _header_mapping(headers)
    if not ({"full_name", "first_name", "company"} & set(mapping)):
        raise CustomerCsvError("No customer-name column was recognized. Include Name, Customer Name, First Name, or Company.")

    raw_rows: list[dict[str, str]] = []
    for row_number, raw in enumerate(reader, start=2):
        if row_number > MAX_CUSTOMER_ROWS + 1:
            raise CustomerCsvError(f"The CSV exceeds {MAX_CUSTOMER_ROWS:,} customer rows.")
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw.items()}
        if any(row.values()):
            row["__row_number__"] = str(row_number)
            raw_rows.append(row)

    locality_values: list[str] = []
    for row in raw_rows:
        locality_values.append(_value(row, mapping, "mailing_address"))
        locality_values.append(_value(row, mapping, "property_address"))
    localities = _discover_localities(locality_values)

    source_fingerprint = _fingerprint(data)
    row_records: list[dict[str, Any]] = []
    row_warnings: list[str] = []
    skipped_rows: list[int] = []

    for raw in raw_rows:
        row_number = int(raw.pop("__row_number__"))
        first_name = _value(raw, mapping, "first_name")
        last_name = _value(raw, mapping, "last_name")
        full_name = _value(raw, mapping, "full_name")
        company = _value(raw, mapping, "company")
        if not first_name and not last_name and full_name:
            first_name, last_name = _split_name(full_name)
        name = " ".join(value for value in (first_name, last_name) if value).strip() or full_name or company
        if not name:
            skipped_rows.append(row_number)
            row_warnings.append(f"Row {row_number}: skipped because every customer-name field was empty.")
            continue

        email_raw = _value(raw, mapping, "email")
        email, email_error = _email(email_raw)
        secondary_raw = _value(raw, mapping, "email_secondary")
        email_secondary, secondary_error = _email(secondary_raw)
        if email_error:
            row_warnings.append(f"Row {row_number}: {email_error}")
        if secondary_error:
            row_warnings.append(f"Row {row_number}: secondary {secondary_error.lower()}")

        phone_raw, phone_normalized, phone_key = _phone_parts(_value(raw, mapping, "phone"))
        if phone_raw and len(phone_key) < 10:
            row_warnings.append(f"Row {row_number}: phone number looks incomplete: {phone_raw!r}.")

        country_raw = _value(raw, mapping, "country")
        country = COUNTRY_VALUES.get(normalize_header(country_raw), country_raw or "US")
        mailing_raw = _value(raw, mapping, "mailing_address")
        property_raw = _value(raw, mapping, "property_address") or mailing_raw
        mailing_address = _parse_address(mailing_raw, localities, country)
        if _value(raw, mapping, "mailing_address2"):
            mailing_address["street2"] = _value(raw, mapping, "mailing_address2")
        # Explicit structured columns override a conservative raw-address parse.
        for target, source_key in (("city", "city"), ("state", "state"), ("postal_code", "postal_code")):
            value = _value(raw, mapping, source_key)
            if value:
                mailing_address[target] = value
        service_address = _parse_address(property_raw, localities, country)

        source_status = _value(raw, mapping, "status")
        normalized_status = STATUS_MAP.get(source_status.lower(), source_status.upper().replace(" ", "_") if source_status else "ACTIVE")
        record: dict[str, Any] = {
            "row_number": row_number,
            "external_id": _value(raw, mapping, "external_id"),
            "first_name": first_name,
            "last_name": last_name,
            "name": name,
            "company": company,
            "email": email,
            "email_raw": email_raw,
            "email_error": email_error or "",
            "email_secondary": email_secondary,
            "phone": phone_raw,
            "phone_normalized": phone_normalized,
            "phone_key": phone_key,
            "mailing_address": mailing_address,
            "service_address": service_address,
            "notes": _value(raw, mapping, "notes", lines=True),
            "help_request": _value(raw, mapping, "help_request", lines=True),
            "special_instructions": _value(raw, mapping, "special_instructions", lines=True),
            "property_name": _value(raw, mapping, "property_name"),
            "property_type": _value(raw, mapping, "property_type"),
            "lead_source": _value(raw, mapping, "lead_source"),
            "source_channel": _value(raw, mapping, "source_channel"),
            "source_campaign": _value(raw, mapping, "source_campaign"),
            "source_url": _value(raw, mapping, "source_url"),
            "created_at": _iso_datetime(_value(raw, mapping, "created_at")),
            "last_activity_at": _iso_datetime(_value(raw, mapping, "last_activity_at")),
            "last_activity_action": _value(raw, mapping, "last_activity_action"),
            "next_booking": _iso_datetime(_value(raw, mapping, "next_booking")),
            "assigned_staff": _value(raw, mapping, "assigned_staff"),
            "time_zone": _value(raw, mapping, "time_zone"),
            "preferred_language": _value(raw, mapping, "preferred_language"),
            "review_score": _value(raw, mapping, "review_score"),
            "birthday": _iso_datetime(_value(raw, mapping, "birthday")),
            "referred_by": _value(raw, mapping, "referred_by"),
            "tags": _tags(_value(raw, mapping, "tags")),
            "status": normalized_status,
            "source_status": source_status,
            "unsubscribed": _bool(_value(raw, mapping, "unsubscribed")),
            "email_blocked": _bool(_value(raw, mapping, "email_blocked")),
            "transactional_opt_in": _bool(_value(raw, mapping, "transactional_opt_in")),
            "promotional_opt_in": _bool(_value(raw, mapping, "promotional_opt_in")),
            "pending_estimates_cents": _money_cents(_value(raw, mapping, "pending_estimates_total")),
            "open_payments_cents": _money_cents(_value(raw, mapping, "open_payments_total")),
            "approved_estimates_cents": _money_cents(_value(raw, mapping, "approved_estimates_total")),
            "source_fingerprint": source_fingerprint,
            "source_fields": {header: _plain(raw.get(header, ""), keep_lines=(header == mapping.get("notes"))) for header in headers},
        }
        record["dedupe_key"] = _row_contact_key(record)
        row_records.append(record)

    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for record in row_records:
        groups.setdefault(str(record["dedupe_key"]), []).append(record)
    customers = [_merge_contact(records, key) for key, records in groups.items()]

    property_count = sum(len(customer.get("properties") or []) for customer in customers)
    duplicate_contact_rows = sum(max(0, len(records) - 1) for records in groups.values())
    no_contact_method = sum(1 for item in customers if not item.get("email") and not item.get("phone"))
    needs_review = sum(1 for item in customers if item.get("quality_flags"))
    status_counts: dict[str, int] = {}
    for item in customers:
        value = str(item.get("status") or "UNKNOWN")
        status_counts[value] = status_counts.get(value, 0) + 1

    counts = {
        "rows_read": len(row_records),
        "customers_ready": len(customers),
        "unique_customer_files": len(customers),
        "duplicate_contact_rows_merged": duplicate_contact_rows,
        "duplicate_rows_skipped": duplicate_contact_rows,  # compatibility with older review pages
        "properties_ready": property_count,
        "with_email": sum(1 for item in customers if item.get("email")),
        "with_phone": sum(1 for item in customers if item.get("phone")),
        "with_address": sum(1 for item in customers if item.get("mailing_address", {}).get("raw") or item.get("properties")),
        "without_email_or_phone": no_contact_method,
        "needs_review": needs_review,
        "transactional_opt_in": sum(1 for item in customers if item.get("transactional_opt_in")),
        "promotional_opt_in": sum(1 for item in customers if item.get("promotional_opt_in")),
        "unsubscribed": sum(1 for item in customers if item.get("unsubscribed")),
        "email_blocked": sum(1 for item in customers if item.get("email_blocked")),
        "skipped_rows": len(skipped_rows),
    }
    totals = {
        "historical_pending_estimates_cents": sum(int(item.get("pending_estimates_cents") or 0) for item in customers),
        "historical_open_payments_cents": sum(int(item.get("open_payments_cents") or 0) for item in customers),
        "historical_approved_estimates_cents": sum(int(item.get("approved_estimates_cents") or 0) for item in customers),
    }
    summary = {
        "import_kind": "CUSTOMERS_CSV",
        "import_profile": profile,
        "filename": filename,
        "source_sha256": source_fingerprint,
        "encoding": encoding,
        "headers": headers,
        "column_mapping": mapping,
        "ignored_columns": ignored,
        "preserved_source_columns": headers,
        "counts": counts,
        "status_counts": status_counts,
        "totals": totals,
        "errors": [],
        "warnings": row_warnings[:1000],
        "warning_count": len(row_warnings),
        "skipped_rows": skipped_rows[:1000],
        "status": "PREVIEWED",
    }
    normalized = {
        "import_kind": "CUSTOMERS_CSV",
        "import_profile": profile,
        "source_sha256": source_fingerprint,
        "customers": customers,
    }
    return CustomerCsvResult(summary=summary, normalized=normalized)


def customer_template() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "First Name", "Last Name", "Email", "Country Name", "Address", "Notes", "Time Zone",
        "Preferred Language", "Source", "Source Channel", "Created At", "Unsubscribed", "Email Blocked",
        "Tags", "Last Activity Time", "Assigned Staff", "Next Booking", "Last Activity Action",
        "Opted-in for transactional", "Pending Estimates Total", "Open Payments", "Approved Estimates Total",
        "Status", "I’d like to receive promotional updates", "Email 2", "Property address", "Property type",
        "How can we help you?", "Special instructions/requests", "Property name", "Mobile phone",
    ])
    writer.writerow([
        "Jane", "Example", "jane@example.com", "US", "123 Main Street  Traverse City  MI  49684  USA",
        "Previous waterproofing customer", "America/Detroit", "en", "Initiated by staff", "manual_matter",
        "08/07/2026 09:00", "false", "false", "Referral", "08/07/2026 09:00", "Josh", "", "Customer imported",
        "true", "$0.00 USD", "$0.00 USD", "$0.00 USD", "Existing customer", "false", "",
        "123 Main Street  Traverse City  MI  49684  USA", "Residential", "Crawl space waterproofing",
        "Call before arrival", "Jane Example", "231-555-0101",
    ])
    return output.getvalue().encode("utf-8-sig")
