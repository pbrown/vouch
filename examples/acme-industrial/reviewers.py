"""Simulated reviewers — Priya, Marcus, Diana.

Three responsibilities:
  1. `route_reviewer(task_name, context)` — pick which reviewer sees a draft.
  2. `decide_edit(task_name, reviewer_id, context, agent_output)` — sample
     against the calibrated edit-rate matrix in SIMULATION_SPEC.md and either
     return None (reviewer approves) or a correction dict.
  3. `report_correction(...)` — POST a correction to the runtime, swallowing
     transport errors the same way the SDK swallows capture-POST errors.

All edit logic is rule-based for now. The 70/30 LLM-edit split described in
the spec is deferred — these rules are sufficient to drive the graduation arc
the simulation is designed to demonstrate.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger("acme.reviewers")

# --------------------------------------------------------------------------
# Reviewer ids — must match seed/reviewers.json.
# --------------------------------------------------------------------------

PRIYA = "rev-priya"
MARCUS = "rev-marcus"
DIANA = "rev-diana"


def load_reviewers(seed_dir: Path | None = None) -> list[dict[str, Any]]:
    seed_dir = seed_dir or (Path(__file__).resolve().parent / "seed")
    return json.loads((seed_dir / "reviewers.json").read_text())


# --------------------------------------------------------------------------
# Routing rules.
# --------------------------------------------------------------------------


def route_reviewer(task_name: str, context: dict[str, Any]) -> str:
    """Map (task, context) to a reviewer id, per SIMULATION_SPEC.md."""
    if task_name == "po_acknowledgement":
        if (
            context.get("po_total", 0) >= 25_000
            or context.get("supplier_tier") == "strategic"
        ):
            return PRIYA
        return MARCUS
    if task_name == "supplier_followup":
        if (
            context.get("days_late", 0) >= 7
            or context.get("supplier_tier") == "strategic"
        ):
            return PRIYA
        return MARCUS
    if task_name == "invoice_three_way_match":
        return DIANA
    if task_name == "low_stock_reorder":
        if context.get("estimated_total_cost", 0) >= 25_000:
            return PRIYA
        return MARCUS
    if task_name == "new_supplier_engagement":
        return PRIYA
    raise ValueError(f"unknown task_name: {task_name!r}")


# --------------------------------------------------------------------------
# Edit-rate matrix.
# --------------------------------------------------------------------------

# Routing has already split context (high-value vs routine, etc.), so a flat
# (task, reviewer) key is enough — except for invoice three-way match, where
# Diana sees both clean and discrepancy outputs and the rate flips dramatically.
EDIT_RATES: dict[tuple[str, str], float] = {
    ("po_acknowledgement", MARCUS): 0.02,
    ("po_acknowledgement", PRIYA): 0.08,
    ("supplier_followup", MARCUS): 0.12,
    ("supplier_followup", PRIYA): 0.35,
    ("low_stock_reorder", MARCUS): 0.06,
    ("low_stock_reorder", PRIYA): 0.28,
    ("new_supplier_engagement", PRIYA): 0.42,
}

INVOICE_EDIT_RATES: dict[str, float] = {
    "clean": 0.04,
    "discrepancy": 0.65,
    # missing_data: Diana doesn't auto-edit — she bounces the row back to AP
    # for source documents. No correction recorded.
    "missing_data": 0.0,
}


def _edit_rate(task_name: str, reviewer_id: str, agent_output: dict[str, Any]) -> float:
    if task_name == "invoice_three_way_match":
        status = agent_output.get("match_status", "discrepancy")
        return INVOICE_EDIT_RATES.get(status, 0.30)
    rate = EDIT_RATES.get((task_name, reviewer_id))
    if rate is None:
        raise KeyError(f"no edit rate for ({task_name!r}, {reviewer_id!r})")
    return rate


# --------------------------------------------------------------------------
# Edit functions — one per (task, reviewer, context-flavor) cell.
#
# Each returns the edited output dict (deep-copied). They must never mutate
# their input. Severity and tags are paired with the function in EDIT_FNS.
# --------------------------------------------------------------------------

ASTRA_SIGNOFF_RE = re.compile(
    r"(Best regards|Best|Regards|Sincerely|Thanks)[\s,]*\n?\s*Astra(?:[\s,].*)?$",
    re.IGNORECASE | re.DOTALL,
)
ACME_SIGNOFF = "Best,\nAcme Industrial Procurement"


def marcus_edit_po_ack(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    body = edited.get("body", "")
    if ASTRA_SIGNOFF_RE.search(body):
        body = ASTRA_SIGNOFF_RE.sub(ACME_SIGNOFF, body)
    elif "Acme Industrial Procurement" not in body:
        body = body.rstrip() + "\n\n" + ACME_SIGNOFF
    edited["body"] = body
    return edited


def _is_salutation(para: str) -> bool:
    """Heuristic: short single line ending in `,` or `:` with no sentence-ending punctuation."""
    s = para.strip()
    if "\n" in s or len(s) > 80 or not s:
        return False
    if not (s.endswith(",") or s.endswith(":")):
        return False
    return not any(p in s[:-1] for p in (".", "!", "?"))


def priya_edit_po_ack(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    body = edited.get("body", "")
    paragraphs = body.split("\n\n")
    # Skip a leading salutation paragraph (e.g., "Valley Steel Works,") so we
    # find "Thank you…" wherever the prose actually starts.
    target_idx = 1 if paragraphs and _is_salutation(paragraphs[0]) else 0
    if target_idx < len(paragraphs):
        para = paragraphs[target_idx]
        if para.lstrip().lower().startswith("thank you"):
            sentences = re.split(r"(?<=[.!?])\s+", para.lstrip(), maxsplit=1)
            if len(sentences) == 2:
                paragraphs[target_idx] = sentences[1]
            else:
                # Whole paragraph is one Thank-you sentence — drop the paragraph.
                del paragraphs[target_idx]
    edited["body"] = "\n\n".join(paragraphs)
    return edited


def marcus_edit_supplier_followup(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    body = edited.get("body", "")
    softenings = [
        (r"\bwe need\b", "we'd appreciate"),
        (r"\bPlease respond\b", "Could you please respond"),
        (r"\bASAP\b", "at your earliest convenience"),
        (r"\basap\b", "at your earliest convenience"),
    ]
    for pat, repl in softenings:
        body = re.sub(pat, repl, body)
    edited["body"] = body
    return edited


_ESCALATION_BUMP = {
    "soft": "firm",
    "firm": "urgent",
    "urgent": "executive",
    "executive": "executive",
}


def priya_edit_supplier_followup(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    current = edited.get("escalation_level", "firm")
    edited["escalation_level"] = _ESCALATION_BUMP.get(current, current)
    body = edited.get("body", "")
    body = re.sub(r"\bwe apologi[sz]e[^.]*\.\s*", "", body, flags=re.IGNORECASE)
    body = re.sub(r"\b(I'm |we're )?sorry[^.]*\.\s*", "", body, flags=re.IGNORECASE)
    edited["body"] = body
    return edited


def diana_edit_invoice_clean(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    msg = edited.get("approval_message")
    if isinstance(msg, str) and msg:
        first = re.split(r"(?<=[.!?])\s+", msg, maxsplit=1)[0]
        if not first.endswith((".", "!", "?")):
            first = first.rstrip() + "."
        edited["approval_message"] = first
    return edited


def diana_edit_invoice_discrepancy(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    discrepancies = edited.get("discrepancies") or []
    if discrepancies:
        first = discrepancies[0]
        try:
            po_v = float(first.get("po_value", 0))
            inv_v = float(first.get("invoice_value", 0))
            diff = abs(inv_v - po_v)
            pct = (diff / po_v * 100) if po_v else 0.0
            first["variance_note"] = (
                f"Invoice {first.get('field', 'value')}: ${inv_v:,.2f} vs PO ${po_v:,.2f}; "
                f"variance ${diff:,.2f} ({pct:.1f}%) exceeds tolerance per AP-104."
            )
        except TypeError, ValueError:
            # If the values aren't numeric, leave the discrepancy alone.
            pass
    citations = edited.get("policy_citations") or []
    if "AP-104" not in citations:
        citations = list(citations) + ["AP-104"]
    edited["policy_citations"] = citations
    return edited


def marcus_edit_reorder_routine(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    qty = edited.get("proposed_quantity", 0)
    rounded = max(25, round(qty / 25) * 25) if qty else qty
    edited["proposed_quantity"] = rounded
    unit_cost = edited.get("estimated_unit_cost", 0)
    edited["estimated_total_cost"] = round(rounded * unit_cost, 2)
    # Rationale text intentionally left alone — that mismatch is the realistic
    # Marcus pattern (he edits the number, not the prose).
    return edited


def priya_edit_reorder_capex(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    total = edited.get("estimated_total_cost", 0)
    lead = context.get("lead_time_days", "?")
    burn = context.get("monthly_burn", "?")
    edited["rationale"] = (
        f"${total:,.0f} order; covers {lead}-day lead time at "
        f"{burn}/mo burn. Capex approval required."
    )
    return edited


def priya_edit_new_supplier_engagement(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    edited = copy.deepcopy(output)
    target = context.get("target_supplier_name", "team")
    category = context.get("target_category", "your category")
    contact = context.get("acme_contact_name", "Procurement")
    role = context.get("acme_contact_role", "")
    deadline = edited.get("response_deadline", "the date noted above")
    edited["body"] = (
        f"Hi {target} team,\n\n"
        f"Acme Industrial is exploring sourcing partners in {category} and "
        f"would like to send the attached RFQ for your review. "
        f"We'd appreciate a response by {deadline}; the NDA and spec sheet "
        f"are enclosed.\n\n"
        f"Best,\n{contact}{', ' + role if role else ''}"
    )
    return edited


# (task, reviewer, optional invoice match_status) -> (edit_fn, severity, tags)
EditFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
EDIT_FNS: dict[tuple[str, str, str | None], tuple[EditFn, float, list[str]]] = {
    ("po_acknowledgement", MARCUS, None): (marcus_edit_po_ack, 0.1, ["formatting"]),
    ("po_acknowledgement", PRIYA, None): (priya_edit_po_ack, 0.5, ["tone"]),
    ("supplier_followup", MARCUS, None): (
        marcus_edit_supplier_followup,
        0.2,
        ["tone"],
    ),
    ("supplier_followup", PRIYA, None): (
        priya_edit_supplier_followup,
        0.7,
        ["escalation_level", "tone"],
    ),
    ("invoice_three_way_match", DIANA, "clean"): (
        diana_edit_invoice_clean,
        0.1,
        ["formatting"],
    ),
    ("invoice_three_way_match", DIANA, "discrepancy"): (
        diana_edit_invoice_discrepancy,
        0.7,
        ["factual", "policy"],
    ),
    # No missing_data entry: rate is 0.0, so decide_edit returns None and
    # _lookup_edit_fn is never called for that path.
    ("low_stock_reorder", MARCUS, None): (
        marcus_edit_reorder_routine,
        0.2,
        ["quantity"],
    ),
    ("low_stock_reorder", PRIYA, None): (
        priya_edit_reorder_capex,
        0.6,
        ["rationale", "tone"],
    ),
    ("new_supplier_engagement", PRIYA, None): (
        priya_edit_new_supplier_engagement,
        0.9,
        ["tone", "rewrite"],
    ),
}


def _lookup_edit_fn(
    task_name: str, reviewer_id: str, agent_output: dict[str, Any]
) -> tuple[EditFn, float, list[str]]:
    if task_name == "invoice_three_way_match":
        status = agent_output.get("match_status", "discrepancy")
        key = (task_name, reviewer_id, status)
    else:
        key = (task_name, reviewer_id, None)
    try:
        return EDIT_FNS[key]
    except KeyError as exc:
        raise KeyError(f"no edit function registered for {key!r}") from exc


# --------------------------------------------------------------------------
# decide_edit + report_correction.
# --------------------------------------------------------------------------


def decide_edit(
    task_name: str,
    reviewer_id: str,
    context: dict[str, Any],
    agent_output: dict[str, Any],
) -> dict[str, Any] | None:
    """Sample the edit-rate matrix; return a correction dict or None.

    The returned dict has keys: edited_output, edit_severity, edit_tags.
    """
    rate = _edit_rate(task_name, reviewer_id, agent_output)
    if random.random() >= rate:
        return None
    edit_fn, severity, tags = _lookup_edit_fn(task_name, reviewer_id, agent_output)
    edited = edit_fn(agent_output, context)
    return {
        "edited_output": edited,
        "edit_severity": severity,
        "edit_tags": list(tags),
    }


def report_correction(
    capture_id: str,
    original_output: dict[str, Any],
    edited_output: dict[str, Any],
    severity: float,
    reviewer_id: str,
    tags: list[str],
    runtime_url: str,
    submitted_at: float | None = None,
) -> str | None:
    """POST a correction to the runtime. Returns the correction id, or None on failure."""
    payload = {
        "id": str(uuid.uuid4()),
        "capture_id": capture_id,
        "original_output_json": original_output,
        "edited_output_json": edited_output,
        "edit_severity": severity,
        "reviewer_id": reviewer_id,
        "edit_tags": tags,
        "submitted_at": submitted_at if submitted_at is not None else time.time(),
    }
    url = runtime_url.rstrip("/") + "/v1/corrections"
    try:
        resp = httpx.post(url, json=payload, timeout=2.0)
        resp.raise_for_status()
        return payload["id"]
    except Exception as exc:
        logger.warning("acme: failed to send correction to %s: %s", url, exc)
        return None
