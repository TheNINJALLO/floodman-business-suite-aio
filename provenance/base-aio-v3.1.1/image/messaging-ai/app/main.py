from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .config import get_settings
from .openai_client import OpenAIClassifier
from .policy import deterministic_decision
from .schemas import ClassifyRequest, Decision
from .security import AuthenticationError, verify

settings = get_settings()
app = FastAPI(title="Floodman Messaging AI", version="3.0.0", docs_url=None if settings.production else "/docs")
classifier = OpenAIClassifier(settings) if settings.provider == "openai" else None


@app.on_event("shutdown")
def shutdown() -> None:
    if classifier:
        classifier.close()


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "floodman-messaging-ai", "provider": settings.provider}


@app.post("/internal/v1/classify", response_model=Decision)
async def classify(request: Request) -> Decision:
    body = await request.body()
    try:
        verify(request.headers, body, settings.hmac_keys, settings.max_age_seconds)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    parsed = ClassifyRequest.model_validate_json(body)
    deterministic = deterministic_decision(parsed)
    if deterministic.risk_level == "HIGH" or deterministic.confidence >= 0.94 or classifier is None:
        return deterministic
    try:
        ai = classifier.classify(parsed)
    except Exception:
        # Fail closed. The orchestrator will route this to a person rather than invent an answer.
        return deterministic.model_copy(update={"risk_level": "HIGH", "human_review_required": True, "proposed_action": "NO_ACTION"})
    return ai
