"""Write the three Acme Industrial reviewer personas to reviewers.json.

The three reviewers are specific individuals defined in
docs/planning/SIMULATION_SPEC.md. There are only three and the spec describes
each, so we write the objects directly rather than calling an LLM. The Pydantic
model still validates the shape against the spec's "Reviewer persona shape"
section so any drift fails loudly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

TaskHandle = Literal[
    "high_value_po",
    "strategic_supplier_followup",
    "capex_reorder",
    "routine_po_ack",
    "low_value_reorder",
    "invoice_three_way_match",
    "new_supplier_engagement",
]


class EditStyle(BaseModel):
    tone_preference: str
    length_preference: str
    common_additions: list[str]
    common_removals: list[str]


class Reviewer(BaseModel):
    id: str
    name: str
    role: str
    handles: list[TaskHandle]
    edit_style: EditStyle
    edit_rate_baseline: float = Field(ge=0.0, le=1.0)
    severity_baseline: float = Field(ge=0.0, le=1.0)


REVIEWERS: list[Reviewer] = [
    Reviewer(
        id="rev-priya",
        name="Priya Iyer",
        role="Senior Buyer",
        handles=[
            "high_value_po",
            "strategic_supplier_followup",
            "capex_reorder",
            "new_supplier_engagement",
        ],
        edit_style=EditStyle(
            tone_preference="warm but firm",
            length_preference="concise",
            common_additions=[
                "explicit delivery commitment ask",
                "relationship context",
                "named point of contact",
            ],
            common_removals=[
                "apology language for supplier delays",
                "hedging phrases ('we were hoping', 'if possible')",
            ],
        ),
        edit_rate_baseline=0.18,
        severity_baseline=0.6,
    ),
    Reviewer(
        id="rev-marcus",
        name="Marcus Chen",
        role="Junior Buyer",
        handles=[
            "routine_po_ack",
            "low_value_reorder",
        ],
        edit_style=EditStyle(
            tone_preference="neutral, friendly",
            length_preference="as drafted",
            common_additions=[
                "personal sign-off",
                "acme procurement signature block",
            ],
            common_removals=[
                "overly formal salutations",
            ],
        ),
        edit_rate_baseline=0.04,
        severity_baseline=0.2,
    ),
    Reviewer(
        id="rev-diana",
        name="Diana Okafor",
        role="Accounts Payable Lead",
        handles=[
            "invoice_three_way_match",
        ],
        edit_style=EditStyle(
            tone_preference="precise, policy-grounded",
            length_preference="thorough on discrepancies, terse on clean matches",
            common_additions=[
                "GL category corrections",
                "policy citation (e.g., AP-104 line-item rule)",
                "exact variance amount and percentage",
            ],
            common_removals=[
                "ambiguous category labels",
                "vague approval phrasing on flagged invoices",
            ],
        ),
        edit_rate_baseline=0.22,
        severity_baseline=0.7,
    ),
]


def main() -> int:
    out_path = Path(__file__).parent / "reviewers.json"
    payload = [r.model_dump() for r in REVIEWERS]
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(payload)} reviewers to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
