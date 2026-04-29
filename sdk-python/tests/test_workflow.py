"""Tier-routing tests for @vouch.task with a configured workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import vouch


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
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


def _write_workflow(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(body)
    return p


# --- workflow loading ----------------------------------------------------


def test_load_workflow_parses_yaml(tmp_path: Path) -> None:
    p = _write_workflow(
        tmp_path,
        """
workflow: astra
version: 1
tasks:
  - name: po_acknowledgement
    tier: ai_draft
    mechanism: email
  - name: invoice_match
    tier: auto
    mechanism: api
    sample_qa_rate: 0.10
""",
    )
    wf = vouch.load_workflow(p)
    assert wf.workflow == "astra"
    assert wf.version == 1
    assert len(wf.tasks) == 2
    assert wf.task("invoice_match").sample_qa_rate == 0.10


def test_load_workflow_rejects_duplicate_task_names(tmp_path: Path) -> None:
    p = _write_workflow(
        tmp_path,
        """
workflow: astra
version: 1
tasks:
  - {name: a, tier: ai_draft, mechanism: api}
  - {name: a, tier: auto, mechanism: api}
""",
    )
    with pytest.raises(ValueError, match="duplicate task name"):
        vouch.load_workflow(p)


def test_load_workflow_rejects_bad_sample_qa_rate(tmp_path: Path) -> None:
    p = _write_workflow(
        tmp_path,
        """
workflow: astra
version: 1
tasks:
  - {name: a, tier: auto, mechanism: api, sample_qa_rate: 1.5}
""",
    )
    with pytest.raises(Exception):  # pydantic ValidationError
        vouch.load_workflow(p)


def test_configure_workflow_registers_with_runtime(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    p = _write_workflow(
        tmp_path,
        """
workflow: astra
version: 3
tasks:
  - {name: t1, tier: ai_draft, mechanism: api}
""",
    )
    vouch.configure_workflow(p)
    # First POST goes to /v1/workflows during configure.
    assert sent[0]["url"].endswith("/v1/workflows")
    body = sent[0]["body"]
    assert body["workflow_name"] == "astra"
    assert body["version"] == 3
    assert "yaml_content" in body
    assert body["definition_json"]["tasks"][0]["name"] == "t1"


def test_configure_workflow_swallows_runtime_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_post(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("runtime down")

    monkeypatch.setattr(vouch._client, "post", broken_post)

    p = _write_workflow(
        tmp_path,
        """
workflow: astra
version: 1
tasks: [{name: t, tier: ai_draft, mechanism: api}]
""",
    )
    # Must not raise even when the registration POST blows up.
    wf = vouch.configure_workflow(p)
    assert wf.workflow == "astra"
    assert vouch.get_workflow() is wf


# --- tier routing --------------------------------------------------------


def _configure_simple(tmp_path: Path, **task_overrides: Any) -> Path:
    """Configure a single-task workflow for testing one tier path at a time."""
    base: dict[str, Any] = {
        "name": "t",
        "tier": "ai_draft",
        "mechanism": "api",
    }
    base.update(task_overrides)
    yaml_lines = "\n".join(f"    {k}: {v}" for k, v in base.items())
    p = _write_workflow(
        tmp_path,
        f"""
workflow: w
version: 1
tasks:
  -
{yaml_lines}
""",
    )
    vouch.configure_workflow(p)
    return p


def test_human_only_does_not_invoke_function(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    _configure_simple(tmp_path, tier="human_only")
    sent.clear()  # discard the workflow-registration POST

    invocations = []

    @vouch.task("t")
    def t() -> int:
        invocations.append(1)
        return 42

    with pytest.raises(vouch.HumanOnlyTaskError) as excinfo:
        t()

    assert invocations == []  # function NOT executed
    assert excinfo.value.task_name == "t"
    assert excinfo.value.capture_id

    # A pending_human capture was posted.
    cap_posts = [s for s in sent if s["url"].endswith("/v1/captures")]
    assert len(cap_posts) == 1
    body = cap_posts[0]["body"]
    assert body["status"] == "pending_human"
    assert body["output_json"] is None
    assert body["workflow_name"] == "w"
    assert body["workflow_version"] == 1


def test_ai_draft_invokes_and_captures(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    _configure_simple(tmp_path, tier="ai_draft")
    sent.clear()

    @vouch.task("t")
    def t() -> int:
        return 7

    assert t() == 7
    body = [s["body"] for s in sent if s["url"].endswith("/v1/captures")][0]
    assert body["status"] == "success"
    assert body["output_json"] == {"value": 7}
    assert body["workflow_name"] == "w"
    assert body["workflow_version"] == 1
    assert body["sample_qa_flagged"] is None  # ai_draft never flags


def test_auto_tier_flags_at_configured_rate(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    _configure_simple(tmp_path, tier="auto", sample_qa_rate=0.10)
    sent.clear()

    @vouch.task("t")
    def t() -> int:
        return 1

    n = 1000
    for _ in range(n):
        t()

    bodies = [s["body"] for s in sent if s["url"].endswith("/v1/captures")]
    assert len(bodies) == n
    flagged = sum(1 for b in bodies if b["sample_qa_flagged"])
    # 10% target ± 2pp tolerance over 1000 samples is ~5σ; safe envelope.
    assert 80 <= flagged <= 120, f"expected ~100 flagged, got {flagged}"
    # Every capture is success and tagged.
    for b in bodies:
        assert b["status"] == "success"
        assert b["workflow_name"] == "w"


def test_unknown_task_falls_back_to_ai_draft(
    tmp_path: Path, sent: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    _configure_simple(tmp_path, tier="ai_draft", name="known")
    sent.clear()

    @vouch.task("unknown")
    def unknown() -> int:
        return 99

    with caplog.at_level("WARNING", logger="vouch"):
        assert unknown() == 99

    assert any("not found in workflow" in rec.message for rec in caplog.records), (
        "expected warning for unknown task"
    )

    body = [s["body"] for s in sent if s["url"].endswith("/v1/captures")][0]
    assert body["status"] == "success"  # ai_draft fallback executed the function
    assert body["task_name"] == "unknown"


def test_no_workflow_configured_is_backwards_compatible(
    sent: list[dict[str, Any]],
) -> None:
    # Don't call configure_workflow — pre-Layer-2 behavior expected.
    @vouch.task("t")
    def t() -> int:
        return 5

    assert t() == 5
    body = sent[0]["body"]
    assert body["status"] == "success"
    assert body["workflow_name"] is None
    assert body["workflow_version"] is None
    assert body["sample_qa_flagged"] is None


def test_get_last_sample_qa_flagged_after_auto_run(
    tmp_path: Path, sent: list[dict[str, Any]]
) -> None:
    _configure_simple(tmp_path, tier="auto", sample_qa_rate=1.0)
    sent.clear()

    @vouch.task("t")
    def t() -> int:
        return 1

    t()
    assert vouch.get_last_sample_qa_flagged() is True


def test_get_tier_returns_configured_value(tmp_path: Path) -> None:
    _configure_simple(tmp_path, tier="auto", sample_qa_rate=0.5)
    assert vouch.get_tier("t") == "auto"
    assert vouch.get_tier("nonexistent") is None


def test_get_tier_none_without_workflow() -> None:
    assert vouch.get_tier("any") is None
