"""Vouch SDK: capture agent task invocations and route them by trust tier."""

from __future__ import annotations

import contextvars
import functools
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

import httpx
from pydantic import BaseModel, Field

from vouch.workflow import (
    Mechanism,
    TaskConfig,
    Tier,
    WorkflowDefinition,
    load_workflow,
)

logger = logging.getLogger("vouch")

F = TypeVar("F", bound=Callable[..., Any])

DEFAULT_RUNTIME_URL = "http://localhost:8000"

_client = httpx.Client(timeout=2.0)

_last_capture_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vouch_last_capture_id", default=None
)
_last_sample_qa_flagged: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "vouch_last_sample_qa_flagged", default=None
)

# Module-level workflow state. ``None`` means "not configured" — the SDK then
# behaves as it did pre-Layer-2: every task is captured as ai_draft, no tier
# routing. This keeps existing instrumentation working unchanged.
_workflow: WorkflowDefinition | None = None


class HumanOnlyTaskError(Exception):
    """Raised when a tier=human_only task's wrapper is invoked.

    The wrapped function is NOT executed; a capture is posted with
    status="pending_human" so reviewers can pick the work up.
    """

    def __init__(self, task_name: str, capture_id: str):
        super().__init__(
            f"task {task_name!r} is tier=human_only; not executed (capture_id={capture_id})"
        )
        self.task_name = task_name
        self.capture_id = capture_id


def get_last_capture_id() -> str | None:
    """Return the capture id of the most recent @vouch.task call in this context."""
    return _last_capture_id.get()


def get_last_sample_qa_flagged() -> bool | None:
    """Return whether the most recent auto-tier capture was sampled for QA.

    None if the last call was not auto-tier or no call has happened yet.
    """
    return _last_sample_qa_flagged.get()


def get_tier(task_name: str) -> Tier | None:
    """Return the configured tier for a task, or None if no workflow loaded
    or the task isn't in the workflow."""
    if _workflow is None:
        return None
    cfg = _workflow.task(task_name)
    return cfg.tier if cfg is not None else None


def get_workflow() -> WorkflowDefinition | None:
    return _workflow


class CapturePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_name: str
    input_json: dict[str, Any]
    output_json: dict[str, Any] | None = None
    status: Literal["success", "error", "pending_human"]
    error_message: str | None = None
    started_at: float
    completed_at: float
    workflow_name: str | None = None
    workflow_version: int | None = None
    sample_qa_flagged: bool | None = None


def _to_jsonable(value: Any) -> Any:
    """Coerce an arbitrary Python value into JSON-safe structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return repr(value)


def _runtime_url() -> str:
    return os.environ.get("VOUCH_RUNTIME_URL", DEFAULT_RUNTIME_URL).rstrip("/")


def _send(payload: CapturePayload) -> None:
    """Best-effort POST to the runtime. Never raises."""
    url = f"{_runtime_url()}/v1/captures"
    try:
        _client.post(url, json=payload.model_dump(mode="json"))
    except Exception as exc:
        logger.warning("vouch: failed to send capture to %s: %s", url, exc)


def _register_workflow_with_runtime(
    definition: WorkflowDefinition, raw_yaml: str
) -> None:
    """POST the loaded workflow to the runtime. Never raises.

    The runtime de-duplicates on (workflow_name, version) so this is safe to
    call on every agent startup.
    """
    url = f"{_runtime_url()}/v1/workflows"
    body = {
        "workflow_name": definition.workflow,
        "version": definition.version,
        "yaml_content": raw_yaml,
        "definition_json": definition.model_dump(mode="json"),
    }
    try:
        _client.post(url, json=body)
    except Exception as exc:
        logger.warning("vouch: failed to register workflow at %s: %s", url, exc)


def configure_workflow(path: Path | str) -> WorkflowDefinition:
    """Load a workflow YAML and register it with the runtime.

    Calling this is optional: if the agent never calls ``configure_workflow``,
    every ``@vouch.task`` invocation falls back to ai_draft semantics (capture
    only, function executes normally). This preserves the v0.1 behavior.

    If the runtime is unreachable, registration logs a warning but the workflow
    is still loaded locally so the SDK can route by tier.
    """
    global _workflow
    p = Path(path)
    raw_yaml = p.read_text()
    definition = load_workflow(p)
    _workflow = definition
    _register_workflow_with_runtime(definition, raw_yaml)
    logger.info(
        "vouch: configured workflow %s v%d (%d tasks)",
        definition.workflow,
        definition.version,
        len(definition.tasks),
    )
    return definition


def _workflow_tags() -> dict[str, Any]:
    if _workflow is None:
        return {"workflow_name": None, "workflow_version": None}
    return {
        "workflow_name": _workflow.workflow,
        "workflow_version": _workflow.version,
    }


def task(name: str) -> Callable[[F], F]:
    """Decorator that captures a function's inputs, output, and status, and
    routes by configured trust tier when a workflow has been loaded.

    Tier behavior (when a workflow is configured and contains the task):
    - human_only: function NOT executed; capture posted with status=pending_human;
      raises HumanOnlyTaskError so the caller knows.
    - ai_draft: function executed; capture posted with status=success.
    - auto: function executed; capture posted with status=success and
      sample_qa_flagged set per the task's sample_qa_rate.

    When no workflow is configured, OR the task isn't found in the workflow,
    the wrapper falls back to ai_draft semantics. Missing-task warns once.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cfg = _workflow.task(name) if _workflow is not None else None
            if _workflow is not None and cfg is None:
                logger.warning(
                    "vouch: task %r not found in workflow %r v%d; defaulting to ai_draft",
                    name,
                    _workflow.workflow,
                    _workflow.version,
                )

            tier: Tier = cfg.tier if cfg is not None else "ai_draft"
            tags = _workflow_tags()

            started = time.time()
            input_json: dict[str, Any] = {
                "args": _to_jsonable(list(args)),
                "kwargs": _to_jsonable(dict(kwargs)),
            }

            if tier == "human_only":
                pending = CapturePayload(
                    task_name=name,
                    input_json=input_json,
                    output_json=None,
                    status="pending_human",
                    started_at=started,
                    completed_at=time.time(),
                    sample_qa_flagged=None,
                    **tags,
                )
                _last_capture_id.set(pending.id)
                _last_sample_qa_flagged.set(None)
                _send(pending)
                raise HumanOnlyTaskError(task_name=name, capture_id=pending.id)

            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                err_payload = CapturePayload(
                    task_name=name,
                    input_json=input_json,
                    output_json=None,
                    status="error",
                    error_message=f"{type(exc).__name__}: {exc}",
                    started_at=started,
                    completed_at=time.time(),
                    sample_qa_flagged=None,
                    **tags,
                )
                _last_capture_id.set(err_payload.id)
                _last_sample_qa_flagged.set(None)
                _send(err_payload)
                raise

            coerced = _to_jsonable(result)
            output_json = coerced if isinstance(coerced, dict) else {"value": coerced}

            flagged: bool | None = None
            if tier == "auto":
                rate = cfg.sample_qa_rate if cfg is not None else 0.0
                flagged = random.random() < rate

            ok_payload = CapturePayload(
                task_name=name,
                input_json=input_json,
                output_json=output_json,
                status="success",
                started_at=started,
                completed_at=time.time(),
                sample_qa_flagged=flagged,
                **tags,
            )
            _last_capture_id.set(ok_payload.id)
            _last_sample_qa_flagged.set(flagged)
            _send(ok_payload)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def main() -> None:
    print("Hello from vouch!")


__all__ = [
    "CapturePayload",
    "HumanOnlyTaskError",
    "Mechanism",
    "TaskConfig",
    "Tier",
    "WorkflowDefinition",
    "configure_workflow",
    "get_last_capture_id",
    "get_last_sample_qa_flagged",
    "get_tier",
    "get_workflow",
    "load_workflow",
    "main",
    "task",
]
