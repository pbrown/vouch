"""Vouch runtime: ingests capture and correction payloads from SDKs.

Persistence backed by Postgres via SQLAlchemy. Wire format preserves the
existing API contract: ids are strings (UUIDs), timestamps are float epochs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vouch_runtime.db import get_db
from vouch_runtime.models import Capture, Correction

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


app = FastAPI(title="Vouch Runtime", version="0.1.0")


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid UUID")


def _to_epoch(dt: datetime) -> float:
    return dt.timestamp()


def _from_epoch(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _capture_to_dict(c: Capture) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "task_name": c.task_name,
        "input_json": c.input_json,
        "output_json": c.output_json,
        "model": c.model,
        "prompt_version": c.prompt_version,
        "agent_version": c.agent_version,
        "status": c.status,
        "error_message": c.error_message,
        "started_at": _to_epoch(c.started_at),
        "completed_at": _to_epoch(c.completed_at),
    }


def _correction_to_dict(c: Correction) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "capture_id": str(c.capture_id),
        "original_output_json": c.original_output_json,
        "edited_output_json": c.edited_output_json,
        "edit_severity": c.edit_severity,
        "reviewer_id": c.reviewer_id,
        "edit_tags": list(c.edit_tags),
        "submitted_at": _to_epoch(c.submitted_at),
    }


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    captures_total = db.scalar(select(func.count()).select_from(Capture)) or 0
    corrections_total = db.scalar(select(func.count()).select_from(Correction)) or 0
    return {
        "status": "ok",
        "captures": int(captures_total),
        "corrections": int(corrections_total),
    }


@app.post("/v1/captures")
def post_capture(
    payload: CapturePayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    capture_id = _parse_uuid(payload.id, "id")
    capture = Capture(
        id=capture_id,
        task_name=payload.task_name,
        input_json=payload.input_json,
        output_json=payload.output_json,
        status=payload.status,
        error_message=payload.error_message,
        started_at=_from_epoch(payload.started_at),
        completed_at=_from_epoch(payload.completed_at),
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)
    logger.info(
        "capture id=%s task=%s status=%s duration=%.3fs",
        capture.id,
        capture.task_name,
        capture.status,
        payload.completed_at - payload.started_at,
    )
    return _capture_to_dict(capture)


@app.get("/v1/captures")
def list_captures(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(Capture).order_by(Capture.started_at.desc())).all()
    return {
        "captures": [_capture_to_dict(c) for c in rows],
        "count": len(rows),
    }


@app.post("/v1/corrections")
def post_correction(
    payload: CorrectionPayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    correction_id = _parse_uuid(payload.id, "id")
    capture_id = _parse_uuid(payload.capture_id, "capture_id")

    if db.get(Capture, capture_id) is None:
        raise HTTPException(status_code=404, detail=f"capture {capture_id} not found")

    correction = Correction(
        id=correction_id,
        capture_id=capture_id,
        original_output_json=payload.original_output_json,
        edited_output_json=payload.edited_output_json,
        edit_severity=payload.edit_severity,
        reviewer_id=payload.reviewer_id,
        edit_tags=payload.edit_tags,
        submitted_at=_from_epoch(payload.submitted_at),
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)
    logger.info(
        "correction id=%s capture_id=%s reviewer=%s severity=%.2f tags=%s",
        correction.id,
        correction.capture_id,
        correction.reviewer_id,
        correction.edit_severity,
        correction.edit_tags,
    )
    return {"id": str(correction.id), "stored": True}


@app.get("/v1/corrections")
def list_corrections(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(Correction).order_by(Correction.submitted_at.desc())).all()
    return {
        "corrections": [_correction_to_dict(c) for c in rows],
        "count": len(rows),
    }
