"""Tests for the runtime capture and correction endpoints."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from vouch_runtime.models import Capture, Correction


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _sample_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": _new_uuid(),
        "task_name": "add",
        "input_json": {"args": [1, 2], "kwargs": {}},
        "output_json": {"value": 3},
        "status": "success",
        "error_message": None,
        "started_at": 1.0,
        "completed_at": 2.0,
    }
    base.update(overrides)
    return base


def _sample_correction(capture_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": _new_uuid(),
        "capture_id": capture_id,
        "original_output_json": {"body": "Hi"},
        "edited_output_json": {"body": "Hi there"},
        "edit_severity": 0.3,
        "reviewer_id": "rev-marcus",
        "edit_tags": ["tone"],
        "submitted_at": 100.0,
    }
    base.update(overrides)
    return base


# --- captures ------------------------------------------------------------


def test_health_empty(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "captures": 0, "corrections": 0}


def test_post_then_get_captures(client: TestClient) -> None:
    payload = _sample_payload()
    r = client.post("/v1/captures", json=payload)
    assert r.status_code == 200
    stored = r.json()
    assert stored["task_name"] == "add"
    assert stored["id"] == payload["id"]
    assert stored["started_at"] == 1.0
    assert stored["completed_at"] == 2.0

    r = client.get("/v1/captures")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["captures"][0]["task_name"] == "add"
    assert data["captures"][0]["status"] == "success"
    assert data["captures"][0]["output_json"] == {"value": 3}


def test_health_reports_count_after_post(client: TestClient) -> None:
    client.post("/v1/captures", json=_sample_payload())
    client.post(
        "/v1/captures",
        json=_sample_payload(
            task_name="sub",
            status="error",
            output_json=None,
            error_message="ValueError: nope",
        ),
    )
    r = client.get("/health")
    assert r.json() == {"status": "ok", "captures": 2, "corrections": 0}


def test_rejects_invalid_status(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_payload(status="bogus"))
    assert r.status_code == 422


def test_rejects_non_uuid_id(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_payload(id="not-a-uuid"))
    assert r.status_code == 422


def test_roundtrip_preserves_client_supplied_id(client: TestClient) -> None:
    capture_id = "11111111-1111-1111-1111-111111111111"
    client.post("/v1/captures", json=_sample_payload(id=capture_id))
    r = client.get("/v1/captures")
    assert r.json()["captures"][0]["id"] == capture_id


def test_captures_ordered_by_started_at_desc(client: TestClient) -> None:
    client.post(
        "/v1/captures",
        json=_sample_payload(task_name="first", started_at=1.0, completed_at=2.0),
    )
    client.post(
        "/v1/captures",
        json=_sample_payload(task_name="second", started_at=10.0, completed_at=11.0),
    )
    client.post(
        "/v1/captures",
        json=_sample_payload(task_name="third", started_at=5.0, completed_at=6.0),
    )
    rows = client.get("/v1/captures").json()["captures"]
    assert [r["task_name"] for r in rows] == ["second", "third", "first"]


def test_jsonb_round_trip_preserves_nested_structure(client: TestClient) -> None:
    payload = _sample_payload(
        input_json={
            "args": [{"customer": {"id": 42, "tags": ["vip", "ny"]}}, None, 3.14],
            "flag": True,
            "nested": {"deep": {"deeper": [1, 2, {"k": "v"}]}},
        },
        output_json={"unicode": "héllo 🚀", "numbers": [1, 2.5, -3]},
    )
    client.post("/v1/captures", json=payload)
    rows = client.get("/v1/captures").json()["captures"]
    assert rows[0]["input_json"] == payload["input_json"]
    assert rows[0]["output_json"] == payload["output_json"]


# --- corrections ---------------------------------------------------------


def test_post_correction_returns_id_and_stored_flag(client: TestClient) -> None:
    cap = client.post("/v1/captures", json=_sample_payload()).json()
    r = client.post("/v1/corrections", json=_sample_correction(capture_id=cap["id"]))
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] is True
    assert body["id"]


def test_correction_can_reference_capture_id(client: TestClient) -> None:
    cap = client.post(
        "/v1/captures",
        json=_sample_payload(task_name="po_acknowledgement"),
    ).json()
    corr = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"]),
    ).json()

    listed = client.get("/v1/corrections").json()
    assert listed["count"] == 1
    assert listed["corrections"][0]["capture_id"] == cap["id"]
    assert listed["corrections"][0]["id"] == corr["id"]
    assert listed["corrections"][0]["edit_tags"] == ["tone"]


def test_correction_rejects_unknown_capture_id(client: TestClient) -> None:
    r = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=_new_uuid()),
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_correction_rejects_non_uuid_capture_id(client: TestClient) -> None:
    r = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id="cap-xyz"),
    )
    assert r.status_code == 422


def test_correction_rejects_severity_out_of_range(client: TestClient) -> None:
    cap = client.post("/v1/captures", json=_sample_payload()).json()
    r = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"], edit_severity=1.5),
    )
    assert r.status_code == 422
    r = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"], edit_severity=-0.1),
    )
    assert r.status_code == 422


def test_health_includes_corrections_count(client: TestClient) -> None:
    cap = client.post("/v1/captures", json=_sample_payload()).json()
    client.post("/v1/corrections", json=_sample_correction(capture_id=cap["id"]))
    client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"], reviewer_id="rev-priya"),
    )
    r = client.get("/health").json()
    assert r == {"status": "ok", "captures": 1, "corrections": 2}


def test_correction_cascades_on_capture_delete(
    client: TestClient, db_session: Session
) -> None:
    cap = client.post("/v1/captures", json=_sample_payload()).json()
    client.post("/v1/corrections", json=_sample_correction(capture_id=cap["id"]))
    client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"], reviewer_id="rev-priya"),
    )
    assert db_session.scalar(select(Correction).limit(1)) is not None

    capture = db_session.get(Capture, uuid.UUID(cap["id"]))
    assert capture is not None
    db_session.delete(capture)
    db_session.flush()

    remaining = db_session.scalars(select(Correction)).all()
    assert remaining == []
