from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _keys(raw: str) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        key_id, encoded = item.split(":", 1)
        secret = base64.b64decode(encoded, validate=True)
        if len(secret) < 32:
            raise RuntimeError("AI HMAC keys must be at least 32 bytes")
        result[key_id] = secret
    if not result:
        raise RuntimeError("AI_HMAC_KEYS is required")
    return result


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    production: bool
    hmac_keys: dict[str, bytes]
    max_age_seconds: int
    provider: str
    external_provider_approved: bool
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_timeout_seconds: int
    openai_verify_tls: bool
    max_message_chars: int
    max_history_messages: int

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.getenv("FLOODMAN_ENV", "development").strip().lower()
        provider = os.getenv("MESSAGING_AI_PROVIDER", "deterministic").strip().lower()
        if provider not in {"openai", "deterministic"}:
            raise RuntimeError("MESSAGING_AI_PROVIDER must be openai or deterministic")
        approved = _bool("AI_CUSTOMER_MESSAGING_APPROVED", False)
        key = os.getenv("OPENAI_MESSAGING_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
        if provider == "openai" and not key:
            raise RuntimeError("OPENAI_MESSAGING_API_KEY is required when MESSAGING_AI_PROVIDER=openai")
        if env == "production" and provider == "openai" and not approved:
            raise RuntimeError(
                "AI_CUSTOMER_MESSAGING_APPROVED must be true before using an external AI provider for customer messages"
            )
        return cls(
            environment=env,
            production=env == "production",
            hmac_keys=_keys(os.environ["AI_HMAC_KEYS"]),
            max_age_seconds=int(os.getenv("INTERNAL_HMAC_MAX_AGE_SECONDS", "300")),
            provider=provider,
            external_provider_approved=approved,
            openai_api_key=key,
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_model=os.getenv("OPENAI_MESSAGING_MODEL", os.getenv("OPENAI_MODEL", "gpt-5-mini")),
            openai_timeout_seconds=int(os.getenv("OPENAI_MESSAGING_TIMEOUT_SECONDS", "45")),
            openai_verify_tls=_bool("OPENAI_VERIFY_TLS", True),
            max_message_chars=int(os.getenv("MESSAGING_AI_MAX_MESSAGE_CHARS", "3000")),
            max_history_messages=int(os.getenv("MESSAGING_AI_MAX_HISTORY_MESSAGES", "12")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
