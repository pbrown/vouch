"""Mocked unit tests for astra.py — no live LLM calls."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import astra  # noqa: E402


def _tool_use_response(payload: dict[str, Any]) -> MagicMock:
    """Build an Anthropic-shaped response object with one tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture(autouse=True)
def _silence_vouch_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the @vouch.task decorator from POSTing during tests."""
    monkeypatch.setattr("vouch._send", lambda payload: None)


@pytest.fixture
def fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the Anthropic client with a MagicMock for the duration of a test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = MagicMock()
    monkeypatch.setattr(astra, "_client", client)
    return client


def test_handle_po_ack_returns_pydantic_model(fake_anthropic: MagicMock) -> None:
    fake_anthropic.messages.create.return_value = _tool_use_response(
        {
            "subject": "Re: PO-2026-04001 confirmed",
            "body": "Confirming receipt and the May 8 delivery target.",
            "confirmed_delivery_date": "2026-05-08",
            "flagged_issues": ["supplier proposed May 11 vs PO May 8"],
            "requires_human_review": False,
        }
    )
    out = astra.handle_po_ack(
        supplier_email="confirming receipt, ship May 11",
        po={
            "id": "PO-2026-04001",
            "total": 4250.0,
            "expected_delivery": "2026-05-08",
            "supplier": {
                "name": "Cascade Steel Mills",
                "tier": "strategic",
                "communication_style": "brief, professional",
            },
            "line_items": [{"sku": "ALU-6061", "qty": 200, "unit_price": 21.25}],
        },
    )
    assert isinstance(out, astra.POAck)
    assert out.subject.startswith("Re:")
    assert out.flagged_issues
    fake_anthropic.messages.create.assert_called_once()
    call_kwargs = fake_anthropic.messages.create.call_args.kwargs
    assert call_kwargs["model"] == astra.MODEL
    assert call_kwargs["temperature"] == astra.TEMPERATURE


def test_draft_supplier_followup_returns_pydantic_model(
    fake_anthropic: MagicMock,
) -> None:
    fake_anthropic.messages.create.return_value = _tool_use_response(
        {
            "subject": "PO-2026-03002 — checking on revised ship date",
            "body": "Hi team, can you share a revised ship date?",
            "escalation_level": "firm",
            "requested_response_by": "2026-04-26",
        }
    )
    out = astra.draft_supplier_followup(
        po={"id": "PO-2026-03002", "total": 8000, "expected_delivery": "2026-04-18"},
        days_late=6,
        supplier={
            "name": "Northbridge Semiconductor",
            "tier": "preferred",
            "relationship_years": 5,
            "communication_style": "responsive, casual",
        },
    )
    assert isinstance(out, astra.SupplierFollowup)
    assert out.escalation_level == "firm"


def test_reconcile_invoice_returns_pydantic_model(fake_anthropic: MagicMock) -> None:
    fake_anthropic.messages.create.return_value = _tool_use_response(
        {
            "match_status": "discrepancy",
            "discrepancies": [
                {
                    "field": "line_item_1.unit_price",
                    "po_value": "21.25",
                    "receipt_value": "21.25",
                    "invoice_value": "22.10",
                    "variance_note": "Invoice unit price exceeds PO by $0.85.",
                }
            ],
            "approval_message": None,
            "discrepancy_message": "Line 1 unit price variance flagged per AP-104.",
            "recommended_action": "hold_for_review",
            "policy_citations": ["AP-104"],
        }
    )
    out = astra.reconcile_invoice(
        po={"id": "PO-1", "lines": []},
        receipt={"id": "GR-1", "lines": []},
        invoice={"id": "INV-1", "lines": []},
    )
    assert isinstance(out, astra.InvoiceMatchResult)
    assert out.match_status == "discrepancy"
    assert out.recommended_action == "hold_for_review"
    assert out.discrepancies[0].field == "line_item_1.unit_price"


def test_propose_reorder_returns_pydantic_model(fake_anthropic: MagicMock) -> None:
    """LLM only emits prose; numeric fields are computed in Python."""
    fake_anthropic.messages.create.return_value = _tool_use_response(
        {
            "rationale": "30 days buffer above 30-day lead time at 150/month burn.",
            "proposal_message": "Proposing 300 units from Cascade Steel Mills.",
        }
    )
    out = astra.propose_reorder(
        sku={
            "id": "ALU-6061-T6-1IN",
            "description": "1in 6061-T6 aluminum bar",
            "unit_cost": 21.25,
            "monthly_burn": 150,
            "reorder_threshold": 60,
        },
        current_stock=55,
        supplier={
            "id": "sup-000001",
            "name": "Cascade Steel Mills",
            "tier": "strategic",
            "reliability": 0.92,
            "typical_lead_time_days": 30,
            "communication_style": "brief, professional",
        },
    )
    assert isinstance(out, astra.ReorderProposal)
    # 150 * (30/30 + 1) = 300, no safety stock (reliability >= 0.85),
    # ceil(300/10)*10 = 300.
    assert out.proposed_quantity == 300
    assert out.estimated_total_cost == 300 * 21.25
    assert out.requires_capex_approval is False
    assert out.proposed_supplier_id == "sup-000001"
    assert out.rationale.startswith("30 days buffer")


def test_calc_reorder_quantity_applies_safety_stock_when_unreliable() -> None:
    """Direct-test the formula so future tweaks are caught."""
    # Reliable supplier: no safety stock.
    assert (
        astra._calc_reorder_quantity(
            monthly_burn=100, lead_time_days=30, reliability=0.95
        )
        == 200
    )
    # Unreliable supplier: +15% safety stock, then round up to nearest 10.
    # base = 100 * 2 * 1.15 = 230 -> ceil(230/10)*10 = 230.
    assert (
        astra._calc_reorder_quantity(
            monthly_burn=100, lead_time_days=30, reliability=0.80
        )
        == 230
    )
    # Long lead time: 800 * (45/30 + 1) = 2000, no safety stock at 0.88.
    assert (
        astra._calc_reorder_quantity(
            monthly_burn=800, lead_time_days=45, reliability=0.88
        )
        == 2000
    )


def test_engage_new_supplier_returns_pydantic_model(fake_anthropic: MagicMock) -> None:
    fake_anthropic.messages.create.return_value = _tool_use_response(
        {
            "subject": "Acme Industrial — RFQ on epoxy adhesives",
            "body": "Hi team, Acme Industrial is sourcing epoxy adhesives...",
            "rfq_items": [
                {
                    "description": "Two-part structural epoxy",
                    "quantity": 500,
                    "target_specs": "ASTM D1002 lap shear >= 3000 psi",
                }
            ],
            "response_deadline": "2026-05-08",
            "attachments_to_include": ["NDA-template.pdf", "spec-sheet.pdf"],
        }
    )
    out = astra.engage_new_supplier(
        supplier_request={
            "target_supplier_name": "Pacific Adhesive Solutions",
            "target_category": "adhesives",
            "region": "Pacific Northwest",
            "sourcing_brief": "Structural epoxy for fabrication line.",
            "target_volumes_specs": "500 units/month, ASTM D1002.",
            "acme_contact_name": "Priya Iyer",
            "acme_contact_role": "Senior Buyer",
        }
    )
    assert isinstance(out, astra.NewSupplierEngagement)
    assert len(out.rfq_items) == 1
    assert out.rfq_items[0].quantity == 500


def test_call_structured_raises_when_no_tool_use_block(
    fake_anthropic: MagicMock,
) -> None:
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block]
    fake_anthropic.messages.create.return_value = response
    with pytest.raises(RuntimeError, match="no tool_use block"):
        astra.handle_po_ack(supplier_email="...", po={"supplier": {}})
