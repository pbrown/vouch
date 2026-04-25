"""Astra — the simulated procurement agent for Acme Industrial.

Five task functions, one per procurement workflow described in
`docs/planning/SIMULATION_SPEC.md`. Each function:

  * takes structured input (Pydantic-friendly dicts),
  * calls Claude Haiku 4.5 with a forced-tool-use schema,
  * validates the response through a Pydantic output model,
  * is wrapped by `@vouch.task` so every invocation is captured.

Run the smoke test (with API keys in `.env` or the environment):

    uv run python astra.py
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeVar

import vouch
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

_EXAMPLE_DIR = Path(__file__).resolve().parent
load_dotenv(_EXAMPLE_DIR / ".env")

MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.3
MAX_TOKENS = 2048

_T = TypeVar("_T", bound=BaseModel)
_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = Anthropic()
    return _client


def _call_structured(
    prompt: str,
    output_cls: type[_T],
    tool_description: str,
) -> _T:
    """Force Claude to emit a JSON object matching `output_cls` via tool use."""
    tool_name = f"emit_{output_cls.__name__.lower()}"
    schema = output_cls.model_json_schema()
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return output_cls.model_validate(block.input)
    raise RuntimeError(f"Anthropic response had no tool_use block: {response!r}")


# --------------------------------------------------------------------------
# 1) PO acknowledgement
# --------------------------------------------------------------------------


class POAck(BaseModel):
    subject: str
    body: str
    confirmed_delivery_date: date | None = None
    flagged_issues: list[str] = Field(default_factory=list)
    requires_human_review: bool = False


PO_ACK_PROMPT = """\
You are Astra, the procurement agent for Acme Industrial. A supplier just emailed
back about a purchase order. Draft a structured reply that (a) confirms receipt,
(b) flags any discrepancy between what they said and the PO of record, and
(c) restates the delivery expectation.

Supplier: {supplier_name} (tier: {supplier_tier}, communication style: {comm_style}).
PO: id {po_id}, total ${po_total}, line items: {po_lines}, expected delivery {po_expected_delivery}.

Supplier email:
---
{supplier_email}
---

Match Acme's tone for this supplier tier: strategic = warm and direct,
preferred = professional and crisp, transactional = brief and transactional.

Flagging rules:
- If the supplier proposed a delivery date that differs from the PO by more than
  2 business days, add it to flagged_issues AND set requires_human_review=true
  (Acme has not yet agreed to a slipped date).
- Set requires_human_review=true whenever any flagged issue would change Acme's
  commitment: delivery date, total cost, payment terms, line items, or quantities.
- Set requires_human_review=true if anything in the email is ambiguous about
  quantity, price, or delivery.
- Otherwise, leave requires_human_review=false.
"""


@vouch.task(name="po_acknowledgement")
def handle_po_ack(supplier_email: str, po: dict[str, Any]) -> POAck:
    supplier = po.get("supplier", {})
    prompt = PO_ACK_PROMPT.format(
        supplier_name=supplier.get("name", "Unknown"),
        supplier_tier=supplier.get("tier", "transactional"),
        comm_style=supplier.get("communication_style", "professional"),
        po_id=po.get("id", "PO-UNKNOWN"),
        po_total=po.get("total", 0),
        po_lines=json.dumps(po.get("line_items", [])),
        po_expected_delivery=po.get("expected_delivery", "unspecified"),
        supplier_email=supplier_email,
    )
    return _call_structured(
        prompt,
        POAck,
        "Emit a structured PO acknowledgement reply for the buyer to review.",
    )


# --------------------------------------------------------------------------
# 2) Supplier follow-up on a late order
# --------------------------------------------------------------------------


EscalationLevel = Literal["soft", "firm", "urgent", "executive"]


class SupplierFollowup(BaseModel):
    subject: str
    body: str
    escalation_level: EscalationLevel
    requested_response_by: date


SUPPLIER_FOLLOWUP_PROMPT = """\
You are Astra. An order is past its expected ship date and needs a chase email.
Calibrate tone and escalation by lateness; calibrate phrasing (not the level
itself) by tier.

Today's date: {today}.
Supplier: {supplier_name} (tier: {supplier_tier}, {relationship_years}-year relationship,
communication style: {comm_style}).
PO: id {po_id}, value ${po_total}, expected delivery {po_expected_delivery},
days late: {days_late}.

Escalation level is a function of days_late only:
  days_late <= 3   -> escalation_level="soft": polite check-in, no pressure.
  4 <= days_late <= 7   -> escalation_level="firm": ask for a concrete revised ship date.
  8 <= days_late <= 14  -> escalation_level="urgent": cite contract, request escalation contact.
  days_late >= 15  -> escalation_level="executive": flag for senior-buyer
                      involvement; reference relationship history if strategic.

Phrasing within a level varies by tier:
- strategic: lead with relationship context before the ask, mirror comm_style.
- preferred: professional and crisp, no relationship preamble.
- transactional: get to the point in the first sentence.

requested_response_by (count CALENDAR days from today, {today}):
  soft -> {today} + 3 days
  firm -> {today} + 2 days
  urgent -> {today} + 1 day
  executive -> {today} (same day)
"""


@vouch.task(name="supplier_followup")
def draft_supplier_followup(
    po: dict[str, Any],
    days_late: int,
    supplier: dict[str, Any],
) -> SupplierFollowup:
    prompt = SUPPLIER_FOLLOWUP_PROMPT.format(
        today=date.today().isoformat(),
        supplier_name=supplier.get("name", "Unknown"),
        supplier_tier=supplier.get("tier", "transactional"),
        relationship_years=supplier.get("relationship_years", 0),
        comm_style=supplier.get("communication_style", "professional"),
        po_id=po.get("id", "PO-UNKNOWN"),
        po_total=po.get("total", 0),
        po_expected_delivery=po.get("expected_delivery", "unspecified"),
        days_late=days_late,
    )
    return _call_structured(
        prompt,
        SupplierFollowup,
        "Emit a structured supplier follow-up email draft.",
    )


# --------------------------------------------------------------------------
# 3) Invoice three-way match
# --------------------------------------------------------------------------


class Discrepancy(BaseModel):
    field: str
    po_value: str
    receipt_value: str
    invoice_value: str
    variance_note: str


class InvoiceMatchResult(BaseModel):
    match_status: Literal["clean", "discrepancy", "missing_data"]
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    approval_message: str | None = None
    discrepancy_message: str | None = None
    recommended_action: Literal["approve", "hold_for_review", "reject"]
    policy_citations: list[str] = Field(default_factory=list)


INVOICE_MATCH_PROMPT = """\
You are Astra performing a three-way match between a PO, a goods receipt, and a
supplier invoice for Acme Industrial.

PO (canonical):    {po}
Goods receipt:     {receipt}
Supplier invoice:  {invoice}

Variance thresholds (percentage-only — compute as
abs(invoice - po) / po * 100):
- quantity per line: in tolerance if variance <= 1.0%.
- unit price per line: in tolerance if variance <= 0.5%.
- total: in tolerance if variance <= 0.5%.

A variance that exceeds its threshold is "out of tolerance" -> discrepancy.

match_status:
- "clean": every line item appears in all three docs and every quantity, unit
  price, and total is within tolerance.
- "discrepancy": any line item or value is out of tolerance, OR a line on
  PO+receipt is missing from the invoice, OR a line on the invoice does not
  exist on PO+receipt.
- "missing_data": the goods receipt OR the PO is absent (cannot reconcile).

Policy citations (add to policy_citations whenever the rule fires):
- unit price out of tolerance -> AP-104.
- quantity out of tolerance -> AP-117.
- line on PO+receipt missing from invoice -> AP-122.
- line on invoice not present on PO+receipt -> AP-131.

recommended_action:
- match_status="clean" -> "approve".
- match_status="discrepancy" -> "hold_for_review", UNLESS the supplier id on
  the invoice does not match the PO (then "reject").
- match_status="missing_data" -> "hold_for_review".

For each discrepancy, populate field (e.g. "line_item_2.unit_price"), po_value,
receipt_value, invoice_value, and a one-sentence variance_note that includes
the absolute and percentage variance.

On clean matches, write a 2-3 line approval_message and leave
discrepancy_message null. On discrepancies, write a discrepancy_message that
names the exact lines and the policy citation(s) and leave approval_message
null.
"""


@vouch.task(name="invoice_three_way_match")
def reconcile_invoice(
    po: dict[str, Any],
    receipt: dict[str, Any],
    invoice: dict[str, Any],
) -> InvoiceMatchResult:
    prompt = INVOICE_MATCH_PROMPT.format(
        po=json.dumps(po),
        receipt=json.dumps(receipt),
        invoice=json.dumps(invoice),
    )
    return _call_structured(
        prompt,
        InvoiceMatchResult,
        "Emit a three-way invoice match result.",
    )


# --------------------------------------------------------------------------
# 4) Low-stock reorder proposal
# --------------------------------------------------------------------------


class ReorderProposal(BaseModel):
    sku_id: str
    proposed_quantity: int
    proposed_supplier_id: str
    estimated_unit_cost: float
    estimated_total_cost: float
    rationale: str
    requires_capex_approval: bool
    proposal_message: str


class _ReorderRationale(BaseModel):
    """LLM-only output for `propose_reorder` — prose fields only.

    Numerical fields (quantity, total cost, capex flag) are computed
    deterministically in Python and merged in after the call. The LLM is
    notoriously bad at arithmetic; doing the math here removes a whole class
    of hallucination where the rationale text and the numbers disagree.
    """

    rationale: str
    proposal_message: str


def _calc_reorder_quantity(
    monthly_burn: int, lead_time_days: int, reliability: float
) -> int:
    """Acme's reorder formula. Lead-time coverage + 30-day buffer; +15% safety
    stock if reliability < 0.85; round up to nearest 10."""
    base = monthly_burn * (lead_time_days / 30 + 1)
    if reliability < 0.85:
        base *= 1.15
    return math.ceil(base / 10) * 10


REORDER_RATIONALE_PROMPT = """\
You are Astra, the procurement agent for Acme Industrial. We have already
computed the reorder quantity using Acme's standard formula. Your job is to
write a concise rationale and a buyer-facing proposal message.

SKU: {sku_id} ({sku_description}), unit cost ${unit_cost}, monthly burn
{monthly_burn} units, current stock {current_stock}, reorder threshold
{reorder_threshold}.
Preferred supplier: {supplier_name} (id {supplier_id}, tier {supplier_tier},
reliability {reliability}, typical lead time {lead_time_days} days).

PRE-CALCULATED FACTS (use these exactly; do not recompute):
- proposed_quantity = {proposed_quantity} units.
  This covers the {lead_time_days}-day lead time plus ~30 days of buffer
  stock; safety stock {safety_stock_clause}.
- estimated_total_cost = ${estimated_total_cost}.
- requires_capex_approval = {capex_flag}
  (true iff estimated_total_cost exceeds Acme's $10,000 capex threshold).

Field rules:
- rationale: ONE sentence justifying proposed_quantity. Cite lead time, burn
  rate, and the safety-stock decision.
- proposal_message: 3-4 sentences addressed to the reviewing BUYER (not the
  supplier). Summarise SKU, proposed_quantity, supplier choice, and whether
  capex approval is required.
"""


@vouch.task(name="low_stock_reorder")
def propose_reorder(
    sku: dict[str, Any],
    current_stock: int,
    supplier: dict[str, Any],
) -> ReorderProposal:
    monthly_burn = int(sku.get("monthly_burn", 0))
    lead_time_days = int(supplier.get("typical_lead_time_days", 0))
    reliability = float(supplier.get("reliability", 1.0))
    unit_cost = float(sku.get("unit_cost", 0.0))

    proposed_quantity = _calc_reorder_quantity(
        monthly_burn, lead_time_days, reliability
    )
    estimated_total_cost = round(proposed_quantity * unit_cost, 2)
    requires_capex_approval = estimated_total_cost > 10_000
    safety_stock_clause = (
        "applied (+15%) because reliability is below 0.85"
        if reliability < 0.85
        else "not applied (reliability >= 0.85)"
    )

    prompt = REORDER_RATIONALE_PROMPT.format(
        sku_id=sku.get("id", "SKU-UNKNOWN"),
        sku_description=sku.get("description", "unknown"),
        unit_cost=unit_cost,
        monthly_burn=monthly_burn,
        reorder_threshold=sku.get("reorder_threshold", 0),
        current_stock=current_stock,
        supplier_name=supplier.get("name", "Unknown"),
        supplier_id=supplier.get("id", "sup-unknown"),
        supplier_tier=supplier.get("tier", "transactional"),
        reliability=reliability,
        lead_time_days=lead_time_days,
        proposed_quantity=proposed_quantity,
        safety_stock_clause=safety_stock_clause,
        estimated_total_cost=f"{estimated_total_cost:.2f}",
        capex_flag=str(requires_capex_approval).lower(),
    )
    rationale = _call_structured(
        prompt,
        _ReorderRationale,
        "Emit only the rationale and proposal_message text.",
    )

    return ReorderProposal(
        sku_id=str(sku.get("id", "SKU-UNKNOWN")),
        proposed_quantity=proposed_quantity,
        proposed_supplier_id=str(supplier.get("id", "sup-unknown")),
        estimated_unit_cost=unit_cost,
        estimated_total_cost=estimated_total_cost,
        rationale=rationale.rationale,
        requires_capex_approval=requires_capex_approval,
        proposal_message=rationale.proposal_message,
    )


# --------------------------------------------------------------------------
# 5) New supplier engagement
# --------------------------------------------------------------------------


class RFQItem(BaseModel):
    description: str
    quantity: int
    target_specs: str


class NewSupplierEngagement(BaseModel):
    subject: str
    body: str
    rfq_items: list[RFQItem]
    response_deadline: date
    attachments_to_include: list[str] = Field(default_factory=list)


NEW_SUPPLIER_ENGAGEMENT_PROMPT = """\
You are Astra drafting Acme Industrial's first contact with a new supplier
that procurement has identified as a candidate source.

Today's date: {today}.
Supplier under consideration: {target_supplier_name} ({target_category}, region: {region}).
What we want to source: {sourcing_brief}
Target volumes / specs: {target_volumes_specs}
Acme contact: {acme_contact_name}, {acme_contact_role}.

Write a warm but professional intro + RFQ email. Structure of the body:
  1) one paragraph: who Acme is, why we're reaching out, and one specific
     thing we already know about the supplier (drawn from
     {target_supplier_name} or {target_category}).
  2) the ask: an itemised RFQ. EVERY item must populate description, quantity,
     and target_specs. If specs aren't supplied for an item, use the literal
     string "to be confirmed" — never leave specs blank.
  3) close: name {acme_contact_name} as the reply contact. Mention the
     attachments we'll send and the response deadline.

Field rules:
- response_deadline: exactly {today} + 14 calendar days.
- attachments_to_include: always ["NDA-template.pdf", "spec-sheet.pdf"].
  Add others only if a specific need is in the sourcing_brief.

Tone:
- Avoid template-y phrases ("I hope this email finds you well", "Trust this
  email finds you well", etc.).
- Be specific about what makes a strong response: pricing breaks, lead times,
  certifications relevant to {target_category}.
- 4-7 sentences in the body, not counting the RFQ list.
"""


@vouch.task(name="new_supplier_engagement")
def engage_new_supplier(supplier_request: dict[str, Any]) -> NewSupplierEngagement:
    prompt = NEW_SUPPLIER_ENGAGEMENT_PROMPT.format(
        today=date.today().isoformat(),
        target_supplier_name=supplier_request.get("target_supplier_name", "Unknown"),
        target_category=supplier_request.get("target_category", "unknown"),
        region=supplier_request.get("region", "unspecified"),
        sourcing_brief=supplier_request.get("sourcing_brief", ""),
        target_volumes_specs=supplier_request.get("target_volumes_specs", ""),
        acme_contact_name=supplier_request.get("acme_contact_name", "Procurement Team"),
        acme_contact_role=supplier_request.get("acme_contact_role", "Procurement"),
    )
    return _call_structured(
        prompt,
        NewSupplierEngagement,
        "Emit a structured new-supplier intro + RFQ email.",
    )


# --------------------------------------------------------------------------
# Smoke test
# --------------------------------------------------------------------------


def _smoke_test() -> None:
    seed_path = Path(__file__).parent / "seed" / "suppliers.json"
    suppliers = json.loads(seed_path.read_text())
    supplier = next(s for s in suppliers if s["tier"] == "preferred")
    fake_po = {
        "id": "PO-2026-04001",
        "total": 4250.00,
        "expected_delivery": "2026-05-08",
        "supplier": supplier,
        "line_items": [
            {"sku": "ALU-6061-T6-1IN", "qty": 200, "unit_price": 21.25},
        ],
    }
    fake_email = (
        "Hi Acme team, confirming receipt of PO-2026-04001 for 200 units of "
        "1in 6061-T6 aluminum bar. We can ship May 11 via standard freight. "
        "Please confirm net-30 still applies. Thanks."
    )
    print(f"Calling handle_po_ack against supplier: {supplier['name']}")
    result = handle_po_ack(fake_email, fake_po)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    _smoke_test()
