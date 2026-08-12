from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from .http import ProviderError, request_json


class DocumensoClient:
    """Documenso V2 Envelope API adapter.

    Envelope creation is intentionally not transport-retried because a timeout after a
    successful create is ambiguous. The workflow marks that situation for manual review
    instead of risking a duplicate signature request.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.documenso_base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            verify=settings.documenso_verify_tls,
            headers={"authorization": settings.documenso_api_token, "accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def healthcheck(self) -> bool:
        # Authentication is validated during the first real call. This avoids assuming a
        # deployment-specific list endpoint in readiness checks.
        return bool(self.settings.documenso_api_token)

    @staticmethod
    def _field(field: dict[str, Any]) -> dict[str, Any]:
        return {
            "identifier": 0,
            "type": field["field_type"],
            "page": field["page"],
            "positionX": float(field["position_x"]),
            "positionY": float(field["position_y"]),
            "width": float(field["width"]),
            "height": float(field["height"]),
            "required": bool(field.get("required", True)),
        }

    @staticmethod
    def _envelope_id(value: dict[str, Any]) -> str | None:
        candidate = value.get("id") or value.get("envelopeId")
        if candidate:
            return str(candidate)
        envelope = value.get("envelope")
        if isinstance(envelope, dict) and envelope.get("id"):
            return str(envelope["id"])
        return None

    @staticmethod
    def summarize(value: dict[str, Any]) -> dict[str, Any]:
        envelope = value.get("envelope") if isinstance(value.get("envelope"), dict) else value
        recipients = envelope.get("recipients") or []
        items = envelope.get("items") or envelope.get("documents") or []
        signing_url: str | None = envelope.get("signingUrl") or envelope.get("signing_url")
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            signing_url = signing_url or recipient.get("signingUrl") or recipient.get("signing_url")
        item_ids = [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]
        return {
            "id": DocumensoClient._envelope_id(value),
            "status": str(envelope.get("status", value.get("status", "UNKNOWN"))).upper(),
            "signing_url": signing_url,
            "item_ids": item_ids,
            "raw": value,
        }

    def create_and_distribute(
        self,
        *,
        external_id: str,
        title: str,
        recipient_email: str,
        recipient_name: str,
        fields: list[dict[str, Any]],
        pdf: bytes,
        filename: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "DOCUMENT",
            "title": title,
            "externalId": external_id,
            "recipients": [
                {
                    "email": recipient_email,
                    "name": recipient_name,
                    "role": "SIGNER",
                    "fields": [self._field(field) for field in fields],
                }
            ],
            "documentMeta": {
                "subject": self.settings.documenso_default_subject,
                "message": self.settings.documenso_default_message,
                "timezone": "America/Detroit",
            },
        }
        if self.settings.documenso_redirect_url:
            payload["documentMeta"]["redirectUrl"] = self.settings.documenso_redirect_url
        response = request_json(
            self.client,
            "documenso",
            "POST",
            "/envelope/create",
            data={"payload": json.dumps(payload, separators=(",", ":"))},
            files={"files": (filename, pdf, "application/pdf")},
            headers={"authorization": self.settings.documenso_api_token, "accept": "application/json"},
            attempts=1,
            retry_statuses=set(),
        )
        envelope_id = self._envelope_id(response)
        if not envelope_id:
            raise ProviderError("documenso", "envelope create response missing id", details=response)
        distributed = request_json(
            self.client,
            "documenso",
            "POST",
            f"/envelope/{envelope_id}/distribute",
            headers={
                "authorization": self.settings.documenso_api_token,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={},
            attempts=3,
        )
        distributed.setdefault("id", envelope_id)
        summary = self.summarize(distributed)
        if not summary["item_ids"]:
            # The distribute response can be compact. Retrieve once to obtain item IDs.
            retrieved = self.get_envelope(envelope_id)
            summary = self.summarize(retrieved)
            summary["raw"] = {"distributed": distributed, "retrieved": retrieved}
        return summary

    def get_envelope(self, envelope_id: str) -> dict[str, Any]:
        return request_json(
            self.client,
            "documenso",
            "GET",
            f"/envelope/{envelope_id}",
            headers={"authorization": self.settings.documenso_api_token, "accept": "application/json"},
        )

    def download_item(self, item_id: str) -> bytes:
        response = self.client.get(
            f"/envelope/item/{item_id}/download",
            headers={"authorization": self.settings.documenso_api_token, "accept": "application/pdf"},
        )
        if response.is_error:
            raise ProviderError(
                "documenso", "signed PDF download failed", response.status_code, response.text[:2000]
            )
        if not response.content.startswith(b"%PDF-"):
            raise ProviderError("documenso", "downloaded signed document is not a PDF")
        return response.content
