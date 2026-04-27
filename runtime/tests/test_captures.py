"""Tests for the runtime capture endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from vouch_runtime.app import _captures, _corrections, app


@pytest.fixture(autouse=True)
def _clear_state() -> Iterator[None]:
    _captures.clear()
    _corrections.clear()
    yield
    _captures.clear()
    _corrections.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
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


def test_health_empty(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "captures": 0, "corrections": 0}


def test_post_then_get_captures(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_payload())
    assert r.status_code == 200
    stored = r.json()
    assert stored["task_name"] == "add"
    assert stored["id"]  # runtime generated a UUID

    r = client.get("/v1/captures")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["captures"][0]["task_name"] == "add"
    assert data["captures"][0]["status"] == "success"
    assert data["captures"][0]["output_json"] == {"value": 3}


def test_health_reports_count_after_post(client: TestClient) -> None:
    client.post("/v1/captures", json=_sample_payload())
    client.post("/v1/captures", json=_sample_payload(task_name="sub", status="error",
                                                    output_json=None,
                                                    error_message="ValueError: nope"))
    r = client.get("/health")
    assert r.json() == {"status": "ok", "captures": 2, "corrections": 0}


def test_rejects_invalid_status(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_payload(status="bogus"))
    assert r.status_code == 422


def test_roundtrip_preserves_client_supplied_id(client: TestClient) -> None:
    payload = _sample_payload(id="11111111-1111-1111-1111-111111111111")
    client.post("/v1/captures", json=payload)
    r = client.get("/v1/captures")
    assert r.json()["captures"][0]["id"] == "11111111-1111-1111-1111-111111111111"


# --- corrections ---------------------------------------------------------


def _sample_correction(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "capture_id": "cap-abc",
        "original_output_json": {"body": "Hi"},
        "edited_output_json": {"body": "Hi there"},
        "edit_severity": 0.3,
        "reviewer_id": "rev-marcus",
        "edit_tags": ["tone"],
        "submitted_at": 100.0,
    }
    base.update(overrides)
    return base


def test_post_correction_returns_id_and_stored_flag(client: TestClient) -> None:
    r = client.post("/v1/corrections", json=_sample_correction())
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] is True
    assert body["id"]


def test_correction_can_reference_capture_id(client: TestClient) -> None:
    cap = client.post(
        "/v1/captures",
        json=_sample_payload(id="cap-xyz", task_name="po_acknowledgement"),
    ).json()
    corr = client.post(
        "/v1/corrections",
        json=_sample_correction(capture_id=cap["id"]),
    ).json()

    listed = client.get("/v1/corrections").json()
    assert listed["count"] == 1
    assert listed["corrections"][0]["capture_id"] == cap["id"]
    assert listed["corrections"][0]["id"] == corr["id"]


def test_correction_rejects_severity_out_of_range(client: TestClient) -> None:
    r = client.post("/v1/corrections", json=_sample_correction(edit_severity=1.5))
    assert r.status_code == 422
    r = client.post("/v1/corrections", json=_sample_correction(edit_severity=-0.1))
    assert r.status_code == 422


def test_health_includes_corrections_count(client: TestClient) -> None:
    client.post("/v1/captures", json=_sample_payload())
    client.post("/v1/corrections", json=_sample_correction())
    client.post("/v1/corrections", json=_sample_correction(reviewer_id="rev-priya"))
    r = client.get("/health").json()
    assert r == {"status": "ok", "captures": 1, "corrections": 2}
