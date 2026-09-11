from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is empty")
    return value


def _required_if(name: str, enabled: bool) -> str:
    return _required(name) if enabled else os.getenv(name, "").strip()


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    value = int(raw) if raw is not None and raw.strip() else default
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    raw = os.getenv(name)
    value = float(raw) if raw is not None and raw.strip() else default
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _csv(name: str, *, lower: bool = True) -> tuple[str, ...]:
    values = [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]
    return tuple(value.lower() for value in values) if lower else tuple(values)


def _integer_csv(name: str, default: str, minimum: int = 0) -> tuple[int, ...]:
    raw = os.getenv(name, default)
    values: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value < minimum:
            raise RuntimeError(f"Every {name} value must be at least {minimum}")
        values.append(value)
    if not values:
        raise RuntimeError(f"{name} cannot be empty")
    if values != sorted(set(values)):
        raise RuntimeError(f"{name} must contain unique values in ascending order")
    return tuple(values)


def _clock(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    pieces = value.split(":")
    if len(pieces) != 2:
        raise RuntimeError(f"{name} must use HH:MM 24-hour format")
    hour, minute = int(pieces[0]), int(pieces[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RuntimeError(f"{name} must use HH:MM 24-hour format")
    return f"{hour:02d}:{minute:02d}"


def _validate_https(name: str, value: str, production: bool) -> str:
    parsed = urlparse(value)
    if not parsed.hostname:
        raise RuntimeError(f"{name} is not a valid URL")
    if production and parsed.scheme != "https":
        raise RuntimeError(f"{name} must use HTTPS in production")
    return value.rstrip("/")


def parse_hmac_keyring(raw: str) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise RuntimeError("HMAC key entries must be key-id:base64-secret")
        key_id, encoded = entry.split(":", 1)
        try:
            secret = base64.b64decode(encoded, validate=True)
        except Exception as exc:  # pragma: no cover - defensive startup path
            raise RuntimeError(f"HMAC key {key_id!r} is not valid base64") from exc
        if len(secret) < 32:
            raise RuntimeError(f"HMAC key {key_id!r} must be at least 32 bytes")
        if key_id in result:
            raise RuntimeError(f"Duplicate HMAC key id {key_id!r}")
        result[key_id] = secret
    if not result:
        raise RuntimeError("At least one HMAC key is required")
    return result


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    production: bool
    log_level: str
    legal_templates_approved: bool
    sms_compliance_approved: bool
    twilio_a2p_approved: bool
    ai_customer_messaging_approved: bool
    public_base_url: str
    portal_base_url: str
    database_url: str
    db_pool_size: int
    db_max_overflow: int
    documents_path: Path
    max_document_bytes: int
    internal_hmac_keys: dict[str, bytes]
    internal_hmac_max_age_seconds: int
    ai_hmac_keys: dict[str, bytes]
    ai_calling_enabled: bool
    ai_calling_approved: bool
    ai_calling_provider: str
    ai_calling_webhook_url: str
    ai_calling_hmac_keys: dict[str, bytes]
    portal_token_secret: bytes
    portal_token_ttl_seconds: int
    roomflow_document_hosts: tuple[str, ...]
    roomflow_allowed_origins: tuple[str, ...]
    allow_private_document_hosts: bool
    document_require_https: bool
    gauzy_base_url: str
    gauzy_public_url: str
    roomflow_public_url: str
    gauzy_login_path: str
    gauzy_contact_path: str
    gauzy_invoice_path: str
    gauzy_payment_path: str
    gauzy_project_path: str
    gauzy_auto_discover_context: bool
    gauzy_create_property_projects: bool
    gauzy_email: str
    gauzy_password: str
    gauzy_tenant_id: str
    gauzy_organization_id: str
    gauzy_from_organization_id: str
    gauzy_verify_tls: bool
    square_base_url: str
    square_version: str
    square_access_token: str
    square_location_id: str
    square_webhook_signature_key: str
    square_webhook_notification_url: str
    square_delivery_method: str
    square_accept_card: bool
    square_accept_ach: bool
    square_accept_cash_app: bool
    square_verify_tls: bool
    square_split_final_invoice: bool
    documenso_base_url: str
    documenso_api_token: str
    documenso_webhook_secret: str
    documenso_verify_tls: bool
    documenso_default_subject: str
    documenso_default_message: str
    documenso_redirect_url: str | None
    ai_service_url: str
    ai_callback_url: str
    messaging_ai_enabled: bool
    messaging_ai_provider: str
    messaging_ai_service_url: str
    office_internal_url: str
    messaging_ai_min_confidence: float
    messaging_ai_auto_reply_low_risk: bool
    messaging_ai_auto_reply_medium_risk: bool
    twilio_enabled: bool
    twilio_base_url: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_messaging_service_sid: str
    twilio_from_number: str
    twilio_inbound_webhook_url: str
    twilio_status_webhook_url: str
    twilio_verify_tls: bool
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_reply_to: str
    smtp_use_ssl: bool
    smtp_starttls: bool
    ar_enabled: bool
    ar_timezone: str
    ar_scan_seconds: int
    ar_reminder_offsets_hours: tuple[int, ...]
    ar_repeat_interval_hours: int
    ar_max_automated_age_days: int
    ar_send_start_local: str
    ar_send_end_local: str
    ar_digest_local_time: str
    ar_max_sms_per_seven_days: int
    ar_require_sms_consent: bool
    ar_promise_max_days: int
    ar_staff_emails: tuple[str, ...]
    ar_staff_sms_numbers: tuple[str, ...]
    ar_staff_sms_enabled: bool
    outbox_poll_seconds: int
    outbox_max_attempts: int
    outbox_lock_seconds: int
    webhook_max_body_bytes: int
    customer_sms_check_enabled: bool = False
    customer_sms_organization_id: str = "floodman"

    @classmethod
    def from_env(cls) -> Settings:
        environment = os.getenv("FLOODMAN_ENV", "development").strip().lower()
        production = environment == "production"
        portal_secret_raw = _required("PORTAL_TOKEN_SECRET")
        try:
            portal_secret = base64.b64decode(portal_secret_raw, validate=True)
        except Exception as exc:
            raise RuntimeError("PORTAL_TOKEN_SECRET must be base64") from exc
        if len(portal_secret) < 32:
            raise RuntimeError("PORTAL_TOKEN_SECRET must be at least 32 bytes")

        legal_templates_approved = _boolean("LEGAL_TEMPLATES_APPROVED", False)
        sms_compliance_approved = _boolean("SMS_COMPLIANCE_APPROVED", False)
        twilio_a2p_approved = _boolean("TWILIO_A2P_APPROVED", False)
        ai_customer_messaging_approved = _boolean("AI_CUSTOMER_MESSAGING_APPROVED", False)
        ai_calling_enabled = _boolean("AI_CALLING_ENABLED", False)
        ai_calling_approved = _boolean("AI_CALLING_APPROVED", False)
        ai_calling_provider = os.getenv("AI_CALLING_PROVIDER", "deterministic").strip().lower()
        if ai_calling_provider not in {"deterministic"}:
            raise RuntimeError("AI_CALLING_PROVIDER must be deterministic until another reviewed adapter is installed")
        messaging_ai_provider = os.getenv("MESSAGING_AI_PROVIDER", "deterministic").strip().lower()
        if messaging_ai_provider not in {"deterministic", "openai"}:
            raise RuntimeError("MESSAGING_AI_PROVIDER must be deterministic or openai")
        if production and not legal_templates_approved:
            raise RuntimeError("LEGAL_TEMPLATES_APPROVED must be true in production")
        if production and messaging_ai_provider == "openai" and not ai_customer_messaging_approved:
            raise RuntimeError(
                "AI_CUSTOMER_MESSAGING_APPROVED must be true before customer messages may use an external AI provider"
            )
        if production and ai_calling_enabled and not ai_calling_approved:
            raise RuntimeError("AI_CALLING_APPROVED must be true before external call events are enabled in production")

        public_url = _validate_https("PUBLIC_BASE_URL", _required("PUBLIC_BASE_URL"), production)
        ai_calling_webhook_url = os.getenv(
            "AI_CALLING_WEBHOOK_URL",
            f"{public_url}/webhooks/ai-calling/{ai_calling_provider}",
        ).rstrip("/")
        if ai_calling_enabled:
            ai_calling_webhook_url = _validate_https("AI_CALLING_WEBHOOK_URL", ai_calling_webhook_url, production)
            if ai_calling_webhook_url != f"{public_url}/webhooks/ai-calling/{ai_calling_provider}":
                raise RuntimeError("AI_CALLING_WEBHOOK_URL must match the configured provider route")
        square_notification = _validate_https(
            "SQUARE_WEBHOOK_NOTIFICATION_URL", _required("SQUARE_WEBHOOK_NOTIFICATION_URL"), production
        )
        if square_notification != f"{public_url}/webhooks/square":
            raise RuntimeError(
                "SQUARE_WEBHOOK_NOTIFICATION_URL must exactly match PUBLIC_BASE_URL + /webhooks/square"
            )

        twilio_enabled = _boolean("TWILIO_ENABLED", False)
        if production and twilio_enabled and not sms_compliance_approved:
            raise RuntimeError("SMS_COMPLIANCE_APPROVED must be true before Twilio is enabled in production")
        if production and twilio_enabled and not twilio_a2p_approved:
            raise RuntimeError("TWILIO_A2P_APPROVED must be true before Twilio is enabled in production")
        twilio_inbound = os.getenv("TWILIO_INBOUND_WEBHOOK_URL", f"{public_url}/webhooks/twilio/inbound")
        twilio_status = os.getenv("TWILIO_STATUS_WEBHOOK_URL", f"{public_url}/webhooks/twilio/status")
        if twilio_enabled:
            twilio_inbound = _validate_https("TWILIO_INBOUND_WEBHOOK_URL", twilio_inbound, production)
            twilio_status = _validate_https("TWILIO_STATUS_WEBHOOK_URL", twilio_status, production)
            if twilio_inbound != f"{public_url}/webhooks/twilio/inbound":
                raise RuntimeError("TWILIO_INBOUND_WEBHOOK_URL must exactly match PUBLIC_BASE_URL + /webhooks/twilio/inbound")
            if twilio_status != f"{public_url}/webhooks/twilio/status":
                raise RuntimeError("TWILIO_STATUS_WEBHOOK_URL must exactly match PUBLIC_BASE_URL + /webhooks/twilio/status")

        twilio_messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
        twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
        if twilio_enabled and not (twilio_messaging_service_sid or twilio_from_number):
            raise RuntimeError("Set TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM_NUMBER when Twilio is enabled")

        document_path = Path(os.getenv("DOCUMENTS_PATH", "/data/documents")).resolve()
        document_path.mkdir(parents=True, exist_ok=True)
        portal_base_url = _validate_https(
            "PORTAL_BASE_URL", os.getenv("PORTAL_BASE_URL", f"{public_url}/p").rstrip("/"), production
        )
        square_accept_card = _boolean("SQUARE_ACCEPT_CARD", True)
        square_accept_ach = _boolean("SQUARE_ACCEPT_ACH", False)
        square_accept_cash_app = _boolean("SQUARE_ACCEPT_CASH_APP", False)
        if not any((square_accept_card, square_accept_ach, square_accept_cash_app)):
            raise RuntimeError("Enable at least one Square payment method")

        smtp_enabled = _boolean("SMTP_ENABLED", True)
        smtp_use_ssl = _boolean("SMTP_USE_SSL", False)
        smtp_starttls = _boolean("SMTP_STARTTLS", True)
        if smtp_use_ssl and smtp_starttls:
            raise RuntimeError("Choose SMTP_USE_SSL or SMTP_STARTTLS, not both")

        ar_enabled = _boolean("AR_ENABLED", True)
        ar_staff_emails = _csv("AR_STAFF_EMAILS")
        if production and ar_enabled and smtp_enabled and not ar_staff_emails:
            raise RuntimeError("AR_STAFF_EMAILS must contain at least one address in production")

        return cls(
            environment=environment,
            production=production,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            legal_templates_approved=legal_templates_approved,
            sms_compliance_approved=sms_compliance_approved,
            twilio_a2p_approved=twilio_a2p_approved,
            ai_customer_messaging_approved=ai_customer_messaging_approved,
            public_base_url=public_url,
            portal_base_url=portal_base_url,
            database_url=_required("DATABASE_URL"),
            db_pool_size=_integer("DB_POOL_SIZE", 10, 1),
            db_max_overflow=_integer("DB_MAX_OVERFLOW", 10, 0),
            documents_path=document_path,
            max_document_bytes=_integer("MAX_DOCUMENT_BYTES", 25 * 1024 * 1024, 1024),
            internal_hmac_keys=parse_hmac_keyring(_required("INTERNAL_HMAC_KEYS")),
            internal_hmac_max_age_seconds=_integer("INTERNAL_HMAC_MAX_AGE_SECONDS", 300, 30),
            ai_hmac_keys=parse_hmac_keyring(_required("AI_HMAC_KEYS")),
            ai_calling_enabled=ai_calling_enabled,
            ai_calling_approved=ai_calling_approved,
            ai_calling_provider=ai_calling_provider,
            ai_calling_webhook_url=ai_calling_webhook_url,
            ai_calling_hmac_keys=parse_hmac_keyring(
                os.getenv("AI_CALLING_HMAC_KEYS", _required("AI_HMAC_KEYS"))
            ),
            portal_token_secret=portal_secret,
            portal_token_ttl_seconds=_integer("PORTAL_TOKEN_TTL_SECONDS", 30 * 86400, 300),
            roomflow_document_hosts=_csv("ROOMFLOW_DOCUMENT_HOSTS"),
            roomflow_allowed_origins=_csv("ROOMFLOW_ALLOWED_ORIGINS"),
            allow_private_document_hosts=_boolean("ALLOW_PRIVATE_DOCUMENT_HOSTS", False),
            document_require_https=_boolean("DOCUMENT_REQUIRE_HTTPS", True),
            gauzy_base_url=_validate_https("GAUZY_BASE_URL", _required("GAUZY_BASE_URL"), production),
            gauzy_public_url=_validate_https("GAUZY_PUBLIC_URL", os.getenv("GAUZY_PUBLIC_URL", public_url), production),
            roomflow_public_url=_validate_https("ROOMFLOW_PUBLIC_URL", os.getenv("ROOMFLOW_PUBLIC_URL", "https://theninjallo.github.io/roomflow/"), production),
            gauzy_login_path=os.getenv("GAUZY_LOGIN_PATH", "/auth/login"),
            gauzy_contact_path=os.getenv("GAUZY_CONTACT_PATH", "/organization-contact"),
            gauzy_invoice_path=os.getenv("GAUZY_INVOICE_PATH", "/invoices"),
            gauzy_payment_path=os.getenv("GAUZY_PAYMENT_PATH", "/payments"),
            gauzy_project_path=os.getenv("GAUZY_PROJECT_PATH", "/organization-projects"),
            gauzy_auto_discover_context=_boolean("GAUZY_AUTO_DISCOVER_CONTEXT", True),
            gauzy_create_property_projects=_boolean("GAUZY_CREATE_PROPERTY_PROJECTS", True),
            gauzy_email=_required("GAUZY_EMAIL"),
            gauzy_password=_required("GAUZY_PASSWORD"),
            gauzy_tenant_id=os.getenv("GAUZY_TENANT_ID", "AUTO").strip() or "AUTO",
            gauzy_organization_id=os.getenv("GAUZY_ORGANIZATION_ID", "AUTO").strip() or "AUTO",
            gauzy_from_organization_id=os.getenv("GAUZY_FROM_ORGANIZATION_ID", "AUTO").strip() or "AUTO",
            gauzy_verify_tls=_boolean("GAUZY_VERIFY_TLS", True),
            square_base_url=_validate_https(
                "SQUARE_BASE_URL", os.getenv("SQUARE_BASE_URL", "https://connect.squareup.com"), production
            ),
            square_version=os.getenv("SQUARE_VERSION", "2026-07-15"),
            square_access_token=_required("SQUARE_ACCESS_TOKEN"),
            square_location_id=_required("SQUARE_LOCATION_ID"),
            square_webhook_signature_key=_required("SQUARE_WEBHOOK_SIGNATURE_KEY"),
            square_webhook_notification_url=square_notification,
            square_delivery_method=os.getenv("SQUARE_DELIVERY_METHOD", "SHARE_MANUALLY"),
            square_accept_card=square_accept_card,
            square_accept_ach=square_accept_ach,
            square_accept_cash_app=square_accept_cash_app,
            square_verify_tls=_boolean("SQUARE_VERIFY_TLS", True),
            square_split_final_invoice=_boolean("SQUARE_SPLIT_FINAL_INVOICE", True),
            documenso_base_url=_validate_https(
                "DOCUMENSO_BASE_URL", _required("DOCUMENSO_BASE_URL"), production
            ),
            documenso_api_token=_required("DOCUMENSO_API_TOKEN"),
            documenso_webhook_secret=_required("DOCUMENSO_WEBHOOK_SECRET"),
            documenso_verify_tls=_boolean("DOCUMENSO_VERIFY_TLS", True),
            documenso_default_subject=os.getenv(
                "DOCUMENSO_DEFAULT_SUBJECT", "Floodman document ready for signature"
            ),
            documenso_default_message=os.getenv(
                "DOCUMENSO_DEFAULT_MESSAGE", "Please review and complete the attached Floodman document."
            ),
            documenso_redirect_url=os.getenv("DOCUMENSO_REDIRECT_URL") or None,
            ai_service_url=os.getenv("AI_SERVICE_URL", "http://competitor-intel-api:8090").rstrip("/"),
            ai_callback_url=os.getenv("AI_CALLBACK_URL", "http://127.0.0.1:9004/internal/v1/ai/reports"),
            messaging_ai_enabled=_boolean("MESSAGING_AI_ENABLED", True),
            messaging_ai_provider=messaging_ai_provider,
            messaging_ai_service_url=os.getenv("MESSAGING_AI_SERVICE_URL", "http://messaging-ai-api:8100").rstrip("/"),
            office_internal_url=os.getenv("OFFICE_INTERNAL_URL", "http://127.0.0.1:8700").rstrip("/"),
            messaging_ai_min_confidence=_float("MESSAGING_AI_MIN_CONFIDENCE", 0.90),
            messaging_ai_auto_reply_low_risk=_boolean("MESSAGING_AI_AUTO_REPLY_LOW_RISK", True),
            messaging_ai_auto_reply_medium_risk=_boolean("MESSAGING_AI_AUTO_REPLY_MEDIUM_RISK", False),
            twilio_enabled=twilio_enabled,
            twilio_base_url=_validate_https(
                "TWILIO_BASE_URL", os.getenv("TWILIO_BASE_URL", "https://api.twilio.com/2010-04-01"), production
            ),
            twilio_account_sid=_required_if("TWILIO_ACCOUNT_SID", twilio_enabled),
            twilio_auth_token=_required_if("TWILIO_AUTH_TOKEN", twilio_enabled),
            twilio_messaging_service_sid=twilio_messaging_service_sid,
            twilio_from_number=twilio_from_number,
            twilio_inbound_webhook_url=twilio_inbound,
            twilio_status_webhook_url=twilio_status,
            twilio_verify_tls=_boolean("TWILIO_VERIFY_TLS", True),
            smtp_enabled=smtp_enabled,
            smtp_host=_required_if("SMTP_HOST", smtp_enabled),
            smtp_port=_integer("SMTP_PORT", 587, 1),
            smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
            smtp_from_email=_required_if("SMTP_FROM_EMAIL", smtp_enabled),
            smtp_reply_to=os.getenv("SMTP_REPLY_TO", os.getenv("SMTP_FROM_EMAIL", "")).strip(),
            smtp_use_ssl=smtp_use_ssl,
            smtp_starttls=smtp_starttls,
            ar_enabled=ar_enabled,
            ar_timezone=os.getenv("AR_TIMEZONE", "America/Detroit").strip(),
            ar_scan_seconds=_integer("AR_SCAN_SECONDS", 60, 10),
            ar_reminder_offsets_hours=_integer_csv("AR_REMINDER_OFFSETS_HOURS", "24,72,168,336,504,720", 1),
            ar_repeat_interval_hours=_integer("AR_REPEAT_INTERVAL_HOURS", 336, 24),
            ar_max_automated_age_days=_integer("AR_MAX_AUTOMATED_AGE_DAYS", 0, 0),
            ar_send_start_local=_clock("AR_SEND_START_LOCAL", "09:00"),
            ar_send_end_local=_clock("AR_SEND_END_LOCAL", "18:00"),
            ar_digest_local_time=_clock("AR_DIGEST_LOCAL_TIME", "08:00"),
            ar_max_sms_per_seven_days=_integer("AR_MAX_SMS_PER_SEVEN_DAYS", 3, 1),
            ar_require_sms_consent=_boolean("AR_REQUIRE_SMS_CONSENT", True),
            ar_promise_max_days=_integer("AR_PROMISE_MAX_DAYS", 14, 1),
            ar_staff_emails=ar_staff_emails,
            ar_staff_sms_numbers=_csv("AR_STAFF_SMS_NUMBERS", lower=False),
            ar_staff_sms_enabled=_boolean("AR_STAFF_SMS_ENABLED", False),
            outbox_poll_seconds=_integer("OUTBOX_POLL_SECONDS", 2, 1),
            outbox_max_attempts=_integer("OUTBOX_MAX_ATTEMPTS", 8, 1),
            outbox_lock_seconds=_integer("OUTBOX_LOCK_SECONDS", 300, 30),
            webhook_max_body_bytes=_integer("WEBHOOK_MAX_BODY_BYTES", 1024 * 1024, 1024),
            customer_sms_check_enabled=_boolean("CUSTOMER_SMS_CONSENT_CHECK_ENABLED", False),
            customer_sms_organization_id=os.getenv("CUSTOMER_SMS_ORGANIZATION_ID", "floodman").strip(),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
