"""Tests for the simulated reviewers module."""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reviewers  # noqa: E402


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def test_route_po_ack_high_value_to_priya() -> None:
    assert (
        reviewers.route_reviewer(
            "po_acknowledgement",
            {"po_total": 30_000, "supplier_tier": "preferred"},
        )
        == reviewers.PRIYA
    )


def test_route_po_ack_strategic_to_priya_even_when_low_value() -> None:
    assert (
        reviewers.route_reviewer(
            "po_acknowledgement",
            {"po_total": 1_500, "supplier_tier": "strategic"},
        )
        == reviewers.PRIYA
    )


def test_route_po_ack_routine_to_marcus() -> None:
    assert (
        reviewers.route_reviewer(
            "po_acknowledgement",
            {"po_total": 2_000, "supplier_tier": "preferred"},
        )
        == reviewers.MARCUS
    )


def test_route_followup_week_late_to_priya() -> None:
    assert (
        reviewers.route_reviewer(
            "supplier_followup",
            {"days_late": 9, "supplier_tier": "preferred"},
        )
        == reviewers.PRIYA
    )


def test_route_followup_short_late_to_marcus() -> None:
    assert (
        reviewers.route_reviewer(
            "supplier_followup",
            {"days_late": 2, "supplier_tier": "preferred"},
        )
        == reviewers.MARCUS
    )


def test_route_invoice_always_diana() -> None:
    assert reviewers.route_reviewer("invoice_three_way_match", {}) == reviewers.DIANA


def test_route_reorder_capex_to_priya() -> None:
    assert (
        reviewers.route_reviewer("low_stock_reorder", {"estimated_total_cost": 30_000})
        == reviewers.PRIYA
    )


def test_route_reorder_routine_to_marcus() -> None:
    assert (
        reviewers.route_reviewer("low_stock_reorder", {"estimated_total_cost": 1_200})
        == reviewers.MARCUS
    )


def test_route_new_supplier_always_priya() -> None:
    assert reviewers.route_reviewer("new_supplier_engagement", {}) == reviewers.PRIYA


def test_route_unknown_task_raises() -> None:
    with pytest.raises(ValueError, match="unknown task_name"):
        reviewers.route_reviewer("not_a_task", {})


# --------------------------------------------------------------------------
# Edit-rate calibration: sample 1000 times per cell, compare to target.
# --------------------------------------------------------------------------


def _empirical_rate(
    task: str, reviewer: str, output: dict[str, Any], n: int = 1000
) -> float:
    edits = 0
    for _ in range(n):
        if (
            reviewers.decide_edit(task, reviewer, _ctx_for(task, reviewer), output)
            is not None
        ):
            edits += 1
    return edits / n


def _ctx_for(task: str, reviewer: str) -> dict[str, Any]:
    """Minimal context per task, valid for the rule-based edit functions."""
    if task == "po_acknowledgement":
        return {"supplier_tier": "preferred", "po_total": 4000}
    if task == "supplier_followup":
        return {"supplier_tier": "preferred", "days_late": 3}
    if task == "invoice_three_way_match":
        return {}
    if task == "low_stock_reorder":
        return {
            "estimated_total_cost": 30000 if reviewer == reviewers.PRIYA else 1500,
            "lead_time_days": 14,
            "monthly_burn": 100,
        }
    if task == "new_supplier_engagement":
        return {
            "target_supplier_name": "Acme",
            "target_category": "x",
            "acme_contact_name": "Priya",
            "acme_contact_role": "Senior Buyer",
        }
    raise AssertionError(f"unknown task {task!r}")


def test_edit_rates_within_2pct_of_target() -> None:
    """Three (task, reviewer) cells, fixed seed, 1000 samples each, ±2%."""
    random.seed(42)

    cells = [
        # (task, reviewer, agent_output, target_rate)
        (
            "po_acknowledgement",
            reviewers.MARCUS,
            {"subject": "Re: PO", "body": "Confirmed."},
            0.02,
        ),
        (
            "invoice_three_way_match",
            reviewers.DIANA,
            {
                "match_status": "clean",
                "approval_message": "Approved.",
                "discrepancies": [],
            },
            0.04,
        ),
        (
            "new_supplier_engagement",
            reviewers.PRIYA,
            {"subject": "RFQ", "body": "Hello."},
            0.42,
        ),
    ]
    for task, reviewer, output, target in cells:
        rate = _empirical_rate(task, reviewer, output)
        assert abs(rate - target) <= 0.02, (
            f"{task} / {reviewer}: empirical {rate:.3f} not within ±2% of target {target}"
        )


# --------------------------------------------------------------------------
# Edit functions: all produce well-formed dicts and don't crash.
# --------------------------------------------------------------------------


def test_marcus_edit_po_ack_swaps_signoff() -> None:
    out = reviewers.marcus_edit_po_ack(
        {"subject": "Re: PO", "body": "Confirmed.\n\nBest regards, Astra"}, {}
    )
    assert "Acme Industrial Procurement" in out["body"]
    assert "Astra" not in out["body"]


def test_marcus_edit_po_ack_appends_when_no_signoff() -> None:
    out = reviewers.marcus_edit_po_ack({"subject": "Re", "body": "Confirmed."}, {})
    assert out["body"].endswith("Acme Industrial Procurement")


def test_priya_edit_po_ack_drops_thank_you_lead() -> None:
    out = reviewers.priya_edit_po_ack(
        {
            "subject": "Re",
            "body": "Thank you for confirming. We look forward to delivery.\n\nBest,",
        },
        {},
    )
    assert not out["body"].lstrip().lower().startswith("thank you")
    assert "We look forward" in out["body"]


def test_priya_edit_po_ack_skips_leading_salutation() -> None:
    """Regression: when body opens with a salutation paragraph, the rule must
    still find and drop a 'Thank you' sentence in the next paragraph."""
    out = reviewers.priya_edit_po_ack(
        {
            "subject": "Re",
            "body": (
                "Valley Steel Works,\n\n"
                "Thank you for confirming receipt of PO-X. "
                "We acknowledge the order details below.\n\n"
                "Best,\nAstra"
            ),
        },
        {},
    )
    body = out["body"]
    assert "Thank you" not in body
    assert "Valley Steel Works," in body  # salutation preserved
    assert "We acknowledge the order details below." in body


def test_priya_edit_po_ack_drops_paragraph_when_only_thank_you() -> None:
    """If the Thank-you paragraph has only one sentence, drop the whole paragraph."""
    out = reviewers.priya_edit_po_ack(
        {
            "subject": "Re",
            "body": "Customer,\n\nThank you for the email.\n\nDelivery is on track.",
        },
        {},
    )
    assert "Thank you" not in out["body"]
    assert "Delivery is on track." in out["body"]
    assert "Customer," in out["body"]


def test_marcus_edit_supplier_followup_softens() -> None:
    out = reviewers.marcus_edit_supplier_followup(
        {
            "body": "we need a date ASAP. Please respond.",
            "escalation_level": "firm",
            "subject": "x",
            "requested_response_by": "2026-04-30",
        },
        {},
    )
    assert "we'd appreciate" in out["body"]
    assert "Could you please respond" in out["body"]
    assert "ASAP" not in out["body"]


def test_priya_edit_supplier_followup_bumps_escalation() -> None:
    out = reviewers.priya_edit_supplier_followup(
        {
            "body": "We apologize for the inconvenience. Please share an update.",
            "escalation_level": "firm",
            "subject": "x",
            "requested_response_by": "2026-04-30",
        },
        {},
    )
    assert out["escalation_level"] == "urgent"
    assert "apologi" not in out["body"].lower()


def test_priya_edit_supplier_followup_executive_stays() -> None:
    out = reviewers.priya_edit_supplier_followup(
        {
            "body": "x",
            "escalation_level": "executive",
            "subject": "y",
            "requested_response_by": "2026-04-30",
        },
        {},
    )
    assert out["escalation_level"] == "executive"


def test_diana_edit_invoice_clean_trims_to_one_sentence() -> None:
    out = reviewers.diana_edit_invoice_clean(
        {
            "match_status": "clean",
            "approval_message": "Approved for payment. All values match. No issues found.",
            "discrepancies": [],
            "recommended_action": "approve",
            "policy_citations": [],
            "discrepancy_message": None,
        },
        {},
    )
    assert out["approval_message"] == "Approved for payment."


def test_diana_edit_invoice_discrepancy_rewrites_first_variance_note() -> None:
    out = reviewers.diana_edit_invoice_discrepancy(
        {
            "match_status": "discrepancy",
            "approval_message": None,
            "discrepancy_message": "x",
            "recommended_action": "hold_for_review",
            "policy_citations": [],
            "discrepancies": [
                {
                    "field": "line_item_1.unit_price",
                    "po_value": "21.25",
                    "receipt_value": "21.25",
                    "invoice_value": "22.10",
                    "variance_note": "off",
                }
            ],
        },
        {},
    )
    note = out["discrepancies"][0]["variance_note"]
    assert "$22.10" in note and "$21.25" in note and "AP-104" in note
    assert "AP-104" in out["policy_citations"]


def test_marcus_edit_reorder_rounds_to_25() -> None:
    out = reviewers.marcus_edit_reorder_routine(
        {
            "sku_id": "X",
            "proposed_quantity": 308,
            "proposed_supplier_id": "sup-001",
            "estimated_unit_cost": 10.0,
            "estimated_total_cost": 3080.0,
            "rationale": "...",
            "requires_capex_approval": False,
            "proposal_message": "...",
        },
        {},
    )
    assert out["proposed_quantity"] == 300
    assert out["estimated_total_cost"] == 3000.0


def test_priya_edit_reorder_capex_tightens_rationale() -> None:
    out = reviewers.priya_edit_reorder_capex(
        {
            "sku_id": "X",
            "proposed_quantity": 1000,
            "proposed_supplier_id": "sup-001",
            "estimated_unit_cost": 30.0,
            "estimated_total_cost": 30000.0,
            "rationale": "long winded original",
            "requires_capex_approval": True,
            "proposal_message": "...",
        },
        {"lead_time_days": 21, "monthly_burn": 200},
    )
    assert "$30,000" in out["rationale"]
    assert "21-day" in out["rationale"]
    assert "Capex approval required" in out["rationale"]


def test_priya_edit_new_supplier_rewrites_body() -> None:
    out = reviewers.priya_edit_new_supplier_engagement(
        {
            "subject": "RFQ",
            "body": "long verbose template",
            "rfq_items": [],
            "response_deadline": "2026-05-08",
            "attachments_to_include": ["NDA-template.pdf", "spec-sheet.pdf"],
        },
        {
            "target_supplier_name": "Pacific Adhesive Solutions",
            "target_category": "adhesives",
            "acme_contact_name": "Priya Iyer",
            "acme_contact_role": "Senior Buyer",
        },
    )
    assert "Pacific Adhesive Solutions" in out["body"]
    assert "adhesives" in out["body"]
    assert "Priya Iyer" in out["body"]
    assert "2026-05-08" in out["body"]
    # Structural fields untouched.
    assert out["attachments_to_include"] == ["NDA-template.pdf", "spec-sheet.pdf"]


# --------------------------------------------------------------------------
# decide_edit returns shape contract
# --------------------------------------------------------------------------


def test_decide_edit_skips_missing_data_invoices() -> None:
    """Regression: missing_data is not auto-edited (rate=0). Diana bounces
    these back manually for source documents."""
    random.seed(0)
    output = {
        "match_status": "missing_data",
        "discrepancies": [],
        "approval_message": None,
        "discrepancy_message": "Goods receipt missing.",
        "recommended_action": "hold_for_review",
        "policy_citations": [],
    }
    for _ in range(500):
        assert (
            reviewers.decide_edit(
                "invoice_three_way_match", reviewers.DIANA, {}, output
            )
            is None
        )


def test_decide_edit_returns_correction_shape_when_it_fires() -> None:
    random.seed(0)
    # Set rate to 1.0 so we always edit, regardless of seed.
    output = {"subject": "Re", "body": "Confirmed.", "flagged_issues": []}
    while True:
        result = reviewers.decide_edit(
            "po_acknowledgement",
            reviewers.MARCUS,
            {"supplier_tier": "preferred", "po_total": 1000},
            output,
        )
        if result is not None:
            break
    assert set(result.keys()) == {"edited_output", "edit_severity", "edit_tags"}
    assert isinstance(result["edited_output"], dict)
    assert 0.0 <= result["edit_severity"] <= 1.0
    assert isinstance(result["edit_tags"], list)


# --------------------------------------------------------------------------
# Seed JSON sanity
# --------------------------------------------------------------------------


def test_load_reviewers_reads_seed() -> None:
    revs = reviewers.load_reviewers()
    ids = {r["id"] for r in revs}
    assert ids == {reviewers.PRIYA, reviewers.MARCUS, reviewers.DIANA}
