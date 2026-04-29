"""Workflow definition: declarative trust tiers per agent task.

Loaded once at agent startup by ``vouch.configure_workflow(path)``. The SDK's
``@vouch.task`` decorator consults this definition to decide whether to
execute, draft, or refuse to run for each invocation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger("vouch.workflow")

Tier = Literal["human_only", "ai_draft", "auto"]
Mechanism = Literal["email", "api", "computer_use"]


class TaskConfig(BaseModel):
    name: str
    tier: Tier
    mechanism: Mechanism
    sample_qa_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class WorkflowDefinition(BaseModel):
    workflow: str
    version: int = Field(ge=1)
    tasks: list[TaskConfig]

    @field_validator("tasks")
    @classmethod
    def _unique_task_names(cls, tasks: list[TaskConfig]) -> list[TaskConfig]:
        seen: set[str] = set()
        for t in tasks:
            if t.name in seen:
                raise ValueError(f"duplicate task name in workflow: {t.name!r}")
            seen.add(t.name)
        return tasks

    @model_validator(mode="after")
    def _warn_auto_without_qa(self) -> WorkflowDefinition:
        for t in self.tasks:
            if t.tier == "auto" and t.sample_qa_rate == 0.0:
                logger.warning(
                    "task %r is tier=auto with sample_qa_rate=0.0 — no QA sampling",
                    t.name,
                )
        return self

    def task(self, name: str) -> TaskConfig | None:
        for t in self.tasks:
            if t.name == name:
                return t
        return None


def load_workflow(path: Path | str) -> WorkflowDefinition:
    """Read and validate a workflow YAML file."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ValueError(
            f"workflow file {p} must contain a YAML mapping at the top level"
        )
    return WorkflowDefinition.model_validate(raw)
