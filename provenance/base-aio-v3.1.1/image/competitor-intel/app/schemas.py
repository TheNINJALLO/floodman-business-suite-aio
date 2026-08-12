from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TargetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    category: str | None = Field(default=None, max_length=120)
    additional_paths: list[str] = Field(default_factory=list, max_length=10)
    frequency_hours: int = Field(default=168, ge=6, le=8760)


class TargetUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    category: str | None = Field(default=None, max_length=120)
    additional_paths: list[str] | None = Field(default=None, max_length=10)
    frequency_hours: int | None = Field(default=None, ge=6, le=8760)
    enabled: bool | None = None


class RunRequest(StrictModel):
    target_id: str
