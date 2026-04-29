"""Tests for the runtime workflow-versioning endpoints and capture tagging."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _sample_workflow(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "workflow_name": "astra",
        "version": 1,
        "yaml_content": "workflow: astra\nversion: 1\ntasks: []\n",
        "definition_json": {"workflow": "astra", "version": 1, "tasks": []},
    }
    base.update(overrides)
    return base


def _sample_capture(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _new_uuid(),
        "task_name": "t",
        "input_json": {"args": [], "kwargs": {}},
        "output_json": {"value": 1},
        "status": "success",
        "started_at": 1.0,
        "completed_at": 2.0,
    }
    base.update(overrides)
    return base


# --- POST /v1/workflows --------------------------------------------------


def test_register_workflow_creates_row(client: TestClient) -> None:
    r = client.post("/v1/workflows", json=_sample_workflow())
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["id"]
    assert body["workflow"]["workflow_name"] == "astra"
    assert body["workflow"]["version"] == 1


def test_register_workflow_idempotent_on_name_version(client: TestClient) -> None:
    first = client.post("/v1/workflows", json=_sample_workflow()).json()
    # Re-post the same (name, version) — even with different content — gets the
    # original row back. First registration wins.
    second = client.post(
        "/v1/workflows",
        json=_sample_workflow(
            yaml_content="workflow: astra\nversion: 1\ntasks: [{}]\n"
        ),
    ).json()
    assert second["created"] is False
    assert second["id"] == first["id"]


def test_register_workflow_different_versions_create_separate_rows(
    client: TestClient,
) -> None:
    a = client.post("/v1/workflows", json=_sample_workflow(version=1)).json()
    b = client.post("/v1/workflows", json=_sample_workflow(version=2)).json()
    assert a["id"] != b["id"]
    assert a["created"] and b["created"]


def test_register_workflow_rejects_bad_version(client: TestClient) -> None:
    r = client.post("/v1/workflows", json=_sample_workflow(version=0))
    assert r.status_code == 422


# --- GET /v1/workflows/{name}/current and /history -----------------------


def test_get_current_returns_highest_version(client: TestClient) -> None:
    client.post("/v1/workflows", json=_sample_workflow(version=1))
    client.post("/v1/workflows", json=_sample_workflow(version=3))
    client.post("/v1/workflows", json=_sample_workflow(version=2))

    body = client.get("/v1/workflows/astra/current").json()
    assert body["version"] == 3


def test_get_current_404_when_not_registered(client: TestClient) -> None:
    r = client.get("/v1/workflows/nonexistent/current")
    assert r.status_code == 404


def test_get_history_descending_order(client: TestClient) -> None:
    for v in [1, 4, 2, 3]:
        client.post("/v1/workflows", json=_sample_workflow(version=v))

    body = client.get("/v1/workflows/astra/history").json()
    assert body["count"] == 4
    assert [w["version"] for w in body["versions"]] == [4, 3, 2, 1]


def test_get_history_empty_for_unknown_workflow(client: TestClient) -> None:
    body = client.get("/v1/workflows/unknown/history").json()
    assert body == {"workflow_name": "unknown", "count": 0, "versions": []}


def test_history_scoped_to_workflow_name(client: TestClient) -> None:
    client.post("/v1/workflows", json=_sample_workflow(workflow_name="a", version=1))
    client.post("/v1/workflows", json=_sample_workflow(workflow_name="b", version=1))
    client.post("/v1/workflows", json=_sample_workflow(workflow_name="a", version=2))

    a = client.get("/v1/workflows/a/history").json()
    b = client.get("/v1/workflows/b/history").json()
    assert a["count"] == 2
    assert b["count"] == 1


# --- captures: workflow tags persist -------------------------------------


def test_capture_persists_workflow_tags(client: TestClient) -> None:
    payload = _sample_capture(
        workflow_name="astra",
        workflow_version=2,
        sample_qa_flagged=True,
    )
    client.post("/v1/captures", json=payload)
    rows = client.get("/v1/captures").json()["captures"]
    row = rows[0]
    assert row["workflow_name"] == "astra"
    assert row["workflow_version"] == 2
    assert row["sample_qa_flagged"] is True


def test_capture_workflow_tags_optional(client: TestClient) -> None:
    """A capture with no workflow tags still persists (backwards compatible)."""
    client.post("/v1/captures", json=_sample_capture())
    row = client.get("/v1/captures").json()["captures"][0]
    assert row["workflow_name"] is None
    assert row["workflow_version"] is None
    assert row["sample_qa_flagged"] is None


def test_capture_accepts_pending_human_status(client: TestClient) -> None:
    payload = _sample_capture(
        status="pending_human",
        output_json=None,
        workflow_name="astra",
        workflow_version=1,
    )
    r = client.post("/v1/captures", json=payload)
    assert r.status_code == 200
    row = client.get("/v1/captures").json()["captures"][0]
    assert row["status"] == "pending_human"
    assert row["output_json"] is None


def test_capture_rejects_unknown_status(client: TestClient) -> None:
    r = client.post("/v1/captures", json=_sample_capture(status="bogus"))
    assert r.status_code == 422
