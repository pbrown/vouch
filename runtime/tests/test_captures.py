"""Tests for the runtime capture endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from vouch_runtime.app import _captures, app


@pytest.fixture(autouse=True)
def _clear_captures() -> Iterator[None]:
    _captures.clear()
    yield
    _captures.clear()


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
    assert r.json() == {"status": "ok", "captures": 0}


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
    assert r.json() == {"status": "ok", "captures": 2}


def test_rejects_invalid_status(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_payload(status="bogus"))
    assert r.status_code == 422


def test_roundtrip_preserves_client_supplied_id(client: TestClient) -> None:
    payload = _sample_payload(id="11111111-1111-1111-1111-111111111111")
    client.post("/v1/captures", json=payload)
    r = client.get("/v1/captures")
    assert r.json()["captures"][0]["id"] == "11111111-1111-1111-1111-111111111111"
