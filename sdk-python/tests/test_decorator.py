"""Tests for the @vouch.task decorator.

We monkeypatch the module-level httpx.Client.post so no network is touched.
"""

from __future__ import annotations

from typing import Any

import pytest

import vouch


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Reset SDK module-level state for test isolation.

    ContextVars persist across tests in the same thread, and the loaded
    workflow is module-global. Tier-routing tests load a workflow; we must
    not leak it into the legacy decorator tests in this file.
    """
    vouch._last_capture_id.set(None)
    vouch._last_sample_qa_flagged.set(None)
    vouch._workflow = None


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def fake_post(url: str, *, json: Any = None, **_kw: Any) -> Any:
        captured.append({"url": url, "body": json})

        class _Resp:
            status_code = 200

        return _Resp()

    monkeypatch.setattr(vouch._client, "post", fake_post)
    return captured


def test_success_path_captures_payload(sent: list[dict[str, Any]]) -> None:
    @vouch.task("add")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
    assert len(sent) == 1
    body = sent[0]["body"]
    assert sent[0]["url"].endswith("/v1/captures")
    assert body["task_name"] == "add"
    assert body["status"] == "success"
    assert body["input_json"] == {"args": [2, 3], "kwargs": {}}
    assert body["output_json"] == {"value": 5}
    assert body["error_message"] is None
    assert body["started_at"] <= body["completed_at"]
    assert body["id"]  # uuid default factory ran


def test_kwargs_and_dict_output(sent: list[dict[str, Any]]) -> None:
    @vouch.task("make_user")
    def make_user(name: str, *, admin: bool = False) -> dict[str, Any]:
        return {"name": name, "admin": admin}

    make_user("pooja", admin=True)
    body = sent[0]["body"]
    assert body["input_json"] == {"args": ["pooja"], "kwargs": {"admin": True}}
    # dict returns are passed through, not wrapped.
    assert body["output_json"] == {"name": "pooja", "admin": True}


def test_exception_path_records_and_reraises(sent: list[dict[str, Any]]) -> None:
    @vouch.task("boom")
    def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        boom()

    assert len(sent) == 1
    body = sent[0]["body"]
    assert body["task_name"] == "boom"
    assert body["status"] == "error"
    assert body["output_json"] is None
    assert "nope" in body["error_message"]
    assert body["error_message"].startswith("ValueError:")


def test_preserves_function_metadata() -> None:
    @vouch.task("greet")
    def greet(name: str) -> str:
        """Says hi."""
        return f"hi {name}"

    assert greet.__name__ == "greet"
    assert greet.__doc__ == "Says hi."


def test_runtime_failure_does_not_fail_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_post(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr(vouch._client, "post", broken_post)

    @vouch.task("ok")
    def ok() -> int:
        return 42

    # Must not raise even though the transport is broken.
    assert ok() == 42


def test_non_jsonable_inputs_are_coerced(sent: list[dict[str, Any]]) -> None:
    class Widget:
        def __repr__(self) -> str:
            return "<Widget#1>"

    @vouch.task("use_widget")
    def use_widget(w: Widget) -> str:
        return "ok"

    use_widget(Widget())
    body = sent[0]["body"]
    assert body["input_json"]["args"] == ["<Widget#1>"]


def test_runtime_url_env_var(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("VOUCH_RUNTIME_URL", "https://vouch.example.com/")

    @vouch.task("t")
    def t() -> int:
        return 1

    t()
    assert sent[0]["url"] == "https://vouch.example.com/v1/captures"


def test_pydantic_output_serialized_to_dict(sent: list[dict[str, Any]]) -> None:
    """Pydantic returns must land as structured JSON, not a repr() string.

    Reviewers and the graduation engine query individual fields from
    output_json; a repr blob makes that impossible.
    """
    from datetime import date

    from pydantic import BaseModel

    class Reply(BaseModel):
        subject: str
        sent_at: date
        flags: list[str] = []

    @vouch.task("draft_reply")
    def draft_reply() -> Reply:
        return Reply(subject="hi", sent_at=date(2026, 4, 25), flags=["x"])

    draft_reply()
    output_json = sent[0]["body"]["output_json"]
    assert output_json == {
        "subject": "hi",
        "sent_at": "2026-04-25",
        "flags": ["x"],
    }


def test_pydantic_input_serialized_to_dict(sent: list[dict[str, Any]]) -> None:
    """Pydantic args/kwargs must also land as structured JSON, not repr blobs."""
    from pydantic import BaseModel

    class PO(BaseModel):
        id: str
        total: float

    @vouch.task("ack")
    def ack(po: PO) -> str:
        return "ok"

    ack(PO(id="PO-1", total=42.5))
    args = sent[0]["body"]["input_json"]["args"]
    assert args == [{"id": "PO-1", "total": 42.5}]


def test_get_last_capture_id_after_success(sent: list[dict[str, Any]]) -> None:
    @vouch.task("t")
    def t() -> int:
        return 1

    assert vouch.get_last_capture_id() is None  # nothing run yet in this test
    t()
    assert vouch.get_last_capture_id() == sent[0]["body"]["id"]


def test_get_last_capture_id_after_error(sent: list[dict[str, Any]]) -> None:
    @vouch.task("boom")
    def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        boom()
    # Even on error, the id is set so callers can attach a correction if useful.
    assert vouch.get_last_capture_id() == sent[0]["body"]["id"]


def test_get_last_capture_id_isolated_across_threads(
    sent: list[dict[str, Any]],
) -> None:
    """Threads start with fresh contexts; one thread's id does not bleed to another."""
    import threading

    @vouch.task("t")
    def t() -> int:
        return 1

    ids: dict[str, str | None] = {}
    barrier = threading.Barrier(2)

    def worker(label: str) -> None:
        barrier.wait()
        t()
        ids[label] = vouch.get_last_capture_id()

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
    for thr in threads:
        thr.start()
    for thr in threads:
        thr.join()

    assert ids["a"] is not None and ids["b"] is not None
    assert ids["a"] != ids["b"]  # each thread saw its own capture
    # And the parent thread's slot was never written from inside the children.
    assert vouch.get_last_capture_id() is None
