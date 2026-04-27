"""Vouch runtime: ingests capture payloads from SDKs.

In-memory storage is intentional for the capture-loop milestone; Postgres comes
in Week 1. The CapturePayload schema is duplicated from the SDK here — we'll
extract a shared package once the shape stabilizes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("vouch.runtime")


class CapturePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_name: str
    input_json: dict[str, Any]
    output_json: dict[str, Any] | None = None
    status: Literal["success", "error"]
    error_message: str | None = None
    started_at: float
    completed_at: float


class CorrectionPayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capture_id: str
    original_output_json: dict[str, Any]
    edited_output_json: dict[str, Any]
    edit_severity: float = Field(ge=0.0, le=1.0)
    reviewer_id: str
    edit_tags: list[str] = Field(default_factory=list)
    submitted_at: float


# Module-level stores; tests reach in to clear between cases.
_captures: list[CapturePayload] = []
_corrections: list[CorrectionPayload] = []

app = FastAPI(title="Vouch Runtime", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "captures": len(_captures),
        "corrections": len(_corrections),
    }


@app.post("/v1/captures")
def post_capture(payload: CapturePayload) -> CapturePayload:
    _captures.append(payload)
    logger.info(
        "capture id=%s task=%s status=%s duration=%.3fs",
        payload.id,
        payload.task_name,
        payload.status,
        payload.completed_at - payload.started_at,
    )
    return payload


@app.get("/v1/captures")
def list_captures() -> dict[str, Any]:
    return {
        "captures": [c.model_dump(mode="json") for c in _captures],
        "count": len(_captures),
    }


@app.post("/v1/corrections")
def post_correction(payload: CorrectionPayload) -> dict[str, Any]:
    _corrections.append(payload)
    logger.info(
        "correction id=%s capture_id=%s reviewer=%s severity=%.2f tags=%s",
        payload.id,
        payload.capture_id,
        payload.reviewer_id,
        payload.edit_severity,
        payload.edit_tags,
    )
    return {"id": payload.id, "stored": True}


@app.get("/v1/corrections")
def list_corrections() -> dict[str, Any]:
    return {
        "corrections": [c.model_dump(mode="json") for c in _corrections],
        "count": len(_corrections),
    }
