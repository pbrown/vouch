"""Vouch SDK: capture agent task invocations and report them to the runtime."""

from __future__ import annotations

import contextvars
import functools
import logging
import os
import time
import uuid
from typing import Any, Callable, Literal, TypeVar

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("vouch")

F = TypeVar("F", bound=Callable[..., Any])

DEFAULT_RUNTIME_URL = "http://localhost:8000"

# Module-level client for connection pooling. Short timeout: capture is best-effort
# and must not stall the wrapped function if the runtime is slow or unreachable.
_client = httpx.Client(timeout=2.0)

# ContextVar so each thread / asyncio task has its own "most recent capture id"
# slot. Set by the wrapper before _send; read via get_last_capture_id() so
# callers (e.g., reviewers) can attach corrections to a specific capture.
_last_capture_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vouch_last_capture_id", default=None
)


def get_last_capture_id() -> str | None:
    """Return the capture id of the most recent @vouch.task call in this context.

    Returns None if no decorated function has run yet in this context. Note:
    if the runtime POST failed, the id was never persisted server-side, and a
    correction posted against it will be an orphan.
    """
    return _last_capture_id.get()


class CapturePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_name: str
    input_json: dict[str, Any]
    output_json: dict[str, Any] | None = None
    status: Literal["success", "error"]
    error_message: str | None = None
    started_at: float
    completed_at: float


def _to_jsonable(value: Any) -> Any:
    """Coerce an arbitrary Python value into JSON-safe structures.

    Arguments and return values may include ORM rows, dataclasses, or other
    non-serializable objects. We preserve JSON-native types verbatim and fall
    back to repr() for anything else so a capture is always recordable —
    lossy-but-present beats failing the caller.

    Pydantic BaseModel instances are dumped with `mode="json"` so reviewers
    and downstream consumers get structured fields, not a single repr string.
    """
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


def task(name: str) -> Callable[[F], F]:
    """Decorator that captures a function's inputs, output, and status.

    Usage:
        @vouch.task("create_invoice")
        def create_invoice(customer_id: str, amount: int) -> dict: ...

    Captures are POSTed to ${VOUCH_RUNTIME_URL}/v1/captures. Runtime errors
    are swallowed; the wrapped function's own exceptions are recorded and
    re-raised so callers see native behavior.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.time()
            input_json: dict[str, Any] = {
                "args": _to_jsonable(list(args)),
                "kwargs": _to_jsonable(dict(kwargs)),
            }

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
                )
                _last_capture_id.set(err_payload.id)
                _send(err_payload)
                raise

            coerced = _to_jsonable(result)
            # output_json is typed as dict|None, so wrap scalar returns.
            output_json = coerced if isinstance(coerced, dict) else {"value": coerced}

            ok_payload = CapturePayload(
                task_name=name,
                input_json=input_json,
                output_json=output_json,
                status="success",
                started_at=started,
                completed_at=time.time(),
            )
            _last_capture_id.set(ok_payload.id)
            _send(ok_payload)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def main() -> None:
    print("Hello from vouch!")


__all__ = ["CapturePayload", "get_last_capture_id", "main", "task"]
