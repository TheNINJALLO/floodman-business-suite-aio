from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    release: str
    environment: str
    public_url: str
    local_lab_url: str
    engineering_public_url: str
    orchestrator_url: str
    api_public_url: str
    competitor_url: str
    messaging_ai_url: str
    data_dir: str
    documents_dir: str
    internal_hmac_keys: str
    ai_hmac_keys: str
    gauzy_base_url: str
    gauzy_web_url: str
    gauzy_hub_url: str
    gauzy_health_url: str
    gauzy_sync_enabled: bool
    gauzy_tenant_id: str
    gauzy_organization_id: str
    gauzy_from_organization_id: str
    gauzy_admin_email: str
    gauzy_admin_password: str
    gauzy_employee_email: str
    gauzy_employee_password: str
    square_base_url: str
    square_environment: str
    square_application_id: str
    square_web_sdk_url: str
    square_access_token: str
    square_version: str
    square_location_id: str
    square_verify_tls: bool
    customer_public_url: str
    mobile_api_public_url: str
    mobile_token_secret: str
    mobile_access_ttl_seconds: int
    mobile_refresh_ttl_days: int
    payments_enabled: bool
    documenso_base_url: str
    documenso_web_url: str
    documenso_health_url: str
    mailpit_url: str
    mailpit_health_url: str
    roomflow_url: str
    twilio_base_url: str
    twilio_account_sid: str
    smtp_host: str
    smtp_port: int
    ar_timezone: str
    ar_reminder_offsets_hours: str
    ar_repeat_interval_hours: int
    messaging_ai_provider: str
    roomflow_sync_endpoint: str
    auth_enabled: bool
    session_cookie_secure: bool
    max_upload_bytes: int
    call_intake_approval_required: bool = True
    external_portal_api_url: str = ""
    external_portal_api_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            release=os.getenv("FLOODMAN_RELEASE", "windows-business-suite-v3.0.0"),
            environment=os.getenv("FLOODMAN_ENV", "development"),
            public_url=os.getenv("OFFICE_CONSOLE_PUBLIC_URL", "http://localhost:9000").rstrip("/"),
            local_lab_url=os.getenv("LOCAL_LAB_URL", "http://127.0.0.1:9003").rstrip("/"),
            engineering_public_url=os.getenv("LAB_PUBLIC_URL", "http://localhost:9003").rstrip("/"),
            orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:9004").rstrip("/"),
            api_public_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:9004").rstrip("/"),
            competitor_url=os.getenv("COMPETITOR_URL", "http://competitor-intel-api:8090").rstrip("/"),
            messaging_ai_url=os.getenv("MESSAGING_AI_URL", "http://messaging-ai-api:8100").rstrip("/"),
            data_dir=os.getenv("OFFICE_CONSOLE_DATA_DIR", "/data/office"),
            documents_dir=os.getenv("DOCUMENTS_PATH", "/data/documents"),
            internal_hmac_keys=os.getenv("INTERNAL_HMAC_KEYS", ""),
            ai_hmac_keys=os.getenv("AI_HMAC_KEYS", ""),
            gauzy_base_url=os.getenv("GAUZY_FULL_API_URL", "http://gauzy-api:3000/api").rstrip("/"),
            gauzy_web_url=os.getenv("GAUZY_WEB_URL", "http://localhost:9000").rstrip("/"),
            gauzy_hub_url=os.getenv("GAUZY_HUB_URL", "http://localhost:9000").rstrip("/"),
            gauzy_health_url=os.getenv("GAUZY_HEALTH_URL", "http://127.0.0.1:9000/health/live").rstrip("/"),
            gauzy_sync_enabled=_bool("GAUZY_FULL_SYNC_ENABLED", True),
            gauzy_tenant_id=os.getenv("GAUZY_FULL_TENANT_ID", "AUTO").strip(),
            gauzy_organization_id=os.getenv("GAUZY_FULL_ORGANIZATION_ID", "AUTO").strip(),
            gauzy_from_organization_id=os.getenv("GAUZY_FULL_FROM_ORGANIZATION_ID", "AUTO").strip(),
            gauzy_admin_email=os.getenv("GAUZY_ADMIN_EMAIL", os.getenv("GAUZY_OWNER_EMAIL", "")),
            gauzy_admin_password=os.getenv("GAUZY_ADMIN_PASSWORD", os.getenv("GAUZY_OWNER_PASSWORD", "")),
            gauzy_employee_email=os.getenv("GAUZY_EMPLOYEE_EMAIL", ""),
            gauzy_employee_password=os.getenv("GAUZY_EMPLOYEE_PASSWORD", ""),
            square_base_url=os.getenv("SQUARE_BASE_URL", "http://127.0.0.1:9003/square").rstrip("/"),
            square_environment=os.getenv("SQUARE_ENVIRONMENT", "local").strip().lower(),
            square_application_id=os.getenv("SQUARE_APPLICATION_ID", "").strip(),
            square_web_sdk_url=os.getenv("SQUARE_WEB_SDK_URL", "").strip(),
            square_access_token=os.getenv("SQUARE_ACCESS_TOKEN", "local-square-token"),
            square_version=os.getenv("SQUARE_VERSION", "2026-07-15"),
            square_location_id=os.getenv("SQUARE_LOCATION_ID", "local-square-location"),
            square_verify_tls=_bool("SQUARE_VERIFY_TLS", True),
            customer_public_url=os.getenv("FLOODMAN_CUSTOMER_PUBLIC_URL", f"{os.getenv('OFFICE_CONSOLE_PUBLIC_URL', 'http://localhost:9000').rstrip('/')}/customer").rstrip("/"),
            mobile_api_public_url=os.getenv("FLOODMAN_MOBILE_API_PUBLIC_URL", "").rstrip("/"),
            mobile_token_secret=os.getenv("FLOODMAN_MOBILE_TOKEN_SECRET", "").strip(),
            mobile_access_ttl_seconds=int(os.getenv("FLOODMAN_MOBILE_ACCESS_TTL_SECONDS", "900")),
            mobile_refresh_ttl_days=int(os.getenv("FLOODMAN_MOBILE_REFRESH_TTL_DAYS", "30")),
            payments_enabled=_bool("FLOODMAN_PAYMENTS_ENABLED", True),
            documenso_base_url=os.getenv("DOCUMENSO_FULL_API_URL", "http://127.0.0.1:9001/api/v2").rstrip("/"),
            documenso_web_url=os.getenv("DOCUMENSO_WEB_URL", "http://localhost:9001").rstrip("/"),
            documenso_health_url=os.getenv("DOCUMENSO_HEALTH_URL", "http://127.0.0.1:9001").rstrip("/"),
            mailpit_url=os.getenv("MAILPIT_URL", "http://localhost:9002").rstrip("/"),
            mailpit_health_url=os.getenv("MAILPIT_HEALTH_URL", "http://127.0.0.1:9002").rstrip("/"),
            roomflow_url=os.getenv("ROOMFLOW_WEB_URL", "/roomflow/").rstrip("/"),
            twilio_base_url=os.getenv("TWILIO_BASE_URL", "http://127.0.0.1:9003/twilio/2010-04-01"),
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", "ACLOCALFLOODMAN"),
            smtp_host=os.getenv("SMTP_HOST", "127.0.0.1"),
            smtp_port=int(os.getenv("SMTP_PORT", "1025")),
            ar_timezone=os.getenv("AR_TIMEZONE", "America/Detroit"),
            ar_reminder_offsets_hours=os.getenv("AR_REMINDER_OFFSETS_HOURS", "1,2,3,4,5,6"),
            ar_repeat_interval_hours=int(os.getenv("AR_REPEAT_INTERVAL_HOURS", "24")),
            messaging_ai_provider=os.getenv("MESSAGING_AI_PROVIDER", "deterministic"),
            roomflow_sync_endpoint=os.getenv(
                "ROOMFLOW_SYNC_ENDPOINT",
                f"{os.getenv('PUBLIC_BASE_URL', 'http://localhost:9004').rstrip('/')}/internal/v1/jobs/sync-estimate",
            ),
            auth_enabled=_bool("OFFICE_AUTH_ENABLED", True),
            session_cookie_secure=_bool("OFFICE_SESSION_COOKIE_SECURE", False),
            max_upload_bytes=int(os.getenv("OFFICE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            call_intake_approval_required=_bool("CALL_INTAKE_APPROVAL_REQUIRED", True),
            external_portal_api_url=os.getenv("FLOODMAN_PORTAL_API_URL", "").strip(),
            external_portal_api_token=os.getenv("FLOODMAN_PORTAL_API_TOKEN", "").strip(),
        )
