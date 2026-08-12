from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache


def _int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.lower() in {"1", "true", "yes", "on"}


def parse_keys(raw: str) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for entry in raw.split(","):
        if not entry.strip():
            continue
        key_id, encoded = entry.strip().split(":", 1)
        value = base64.b64decode(encoded, validate=True)
        if len(value) < 32:
            raise RuntimeError("AI HMAC keys must contain at least 32 bytes")
        result[key_id] = value
    if not result:
        raise RuntimeError("AI_HMAC_KEYS is required")
    return result


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    hmac_keys: dict[str, bytes]
    hmac_max_age_seconds: int
    callback_url: str
    schedule_seconds: int
    max_runs_per_day: int
    max_pages_per_target: int
    max_response_bytes: int
    max_analysis_chars: int
    user_agent: str
    allow_http: bool
    provider: str
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key or "REPLACE" in key:
            key = None
        return cls(
            database_url=os.environ["AI_DATABASE_URL"],
            hmac_keys=parse_keys(os.environ["AI_HMAC_KEYS"]),
            hmac_max_age_seconds=_int("INTERNAL_HMAC_MAX_AGE_SECONDS", 300, 30),
            callback_url=os.getenv("AI_CALLBACK_URL", "http://127.0.0.1:9004/internal/v1/ai/reports"),
            schedule_seconds=_int("AI_SCHEDULE_SECONDS", 604800, 60),
            max_runs_per_day=_int("AI_MAX_RUNS_PER_DAY", 30, 1),
            max_pages_per_target=_int("AI_MAX_PAGES_PER_TARGET", 5, 1),
            max_response_bytes=_int("AI_MAX_RESPONSE_BYTES", 2 * 1024 * 1024, 1024),
            max_analysis_chars=_int("AI_MAX_ANALYSIS_CHARS", 60000, 1000),
            user_agent=os.getenv("AI_USER_AGENT", "FloodmanCompetitorMonitor/1.0"),
            allow_http=_bool("AI_ALLOW_HTTP", False),
            provider=os.getenv("AI_PROVIDER", "openai").lower(),
            openai_api_key=key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
