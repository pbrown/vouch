"""Acme simulation runner.

Drives Astra through a configurable number of simulated days, captures every
draft via @vouch.task, routes each draft to a simulated reviewer, samples the
calibrated edit-rate matrix, and posts corrections back to the runtime.

Astra's @vouch.task decorator handles capture POSTing automatically; this
runner only needs to (a) invoke Astra and (b) own reviewer routing /
correction reporting.

Usage:
    uv run python runner.py --scenario nominal --days 30 --seed 42
    uv run python runner.py --days 5 --mock   # no live LLM calls
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_EXAMPLE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_EXAMPLE_DIR))


# --------------------------------------------------------------------------
# Mock astra outputs (used when --mock).
#
# Built from the input fields so the resulting captures look plausible even
# when no LLM was called. The point of --mock is to validate the capture +
# correction wiring on a 30-day scenario without burning ~1500 API calls.
# --------------------------------------------------------------------------


def _install_mock_call_structured() -> None:
    """Patch astra._call_structured to return canned, deterministic outputs."""
    import astra

    def fake_call_structured(prompt: str, output_cls: type, _description: str) -> Any:
        if output_cls is astra.POAck:
            return astra.POAck(
                subject="Re: PO confirmed",
                body=(
                    "Thank you for your email. Confirming receipt of the PO and "
                    "the planned delivery date.\n\nBest regards, Astra"
                ),
                confirmed_delivery_date=date(2026, 5, 8),
                flagged_issues=[],
                requires_human_review=False,
            )
        if output_cls is astra.SupplierFollowup:
            return astra.SupplierFollowup(
                subject="Checking in on order status",
                body=(
                    "Hi team, we apologize for the bother. We need an updated "
                    "ship date ASAP. Please respond."
                ),
                escalation_level="firm",
                requested_response_by=date(2026, 4, 30),
            )
        if output_cls is astra.InvoiceMatchResult:
            roll = random.random()
            if roll < 0.70:
                return astra.InvoiceMatchResult(
                    match_status="clean",
                    discrepancies=[],
                    approval_message="Approved for payment. All values match. No issues found.",
                    discrepancy_message=None,
                    recommended_action="approve",
                    policy_citations=[],
                )
            if roll < 0.95:
                return astra.InvoiceMatchResult(
                    match_status="discrepancy",
                    discrepancies=[
                        astra.Discrepancy(
                            field="line_item_1.unit_price",
                            po_value="21.25",
                            receipt_value="21.25",
                            invoice_value="22.10",
                            variance_note="off",
                        )
                    ],
                    approval_message=None,
                    discrepancy_message="Line 1 unit price variance flagged.",
                    recommended_action="hold_for_review",
                    policy_citations=[],
                )
            return astra.InvoiceMatchResult(
                match_status="missing_data",
                discrepancies=[],
                approval_message=None,
                discrepancy_message="Goods receipt missing.",
                recommended_action="hold_for_review",
                policy_citations=[],
            )
        if output_cls is astra._ReorderRationale:
            return astra._ReorderRationale(
                rationale="Covers lead time + 30-day buffer at current burn.",
                proposal_message="Proposing reorder; please review.",
            )
        if output_cls is astra.NewSupplierEngagement:
            return astra.NewSupplierEngagement(
                subject="Acme Industrial — RFQ",
                body="Hi team, long verbose template body...",
                rfq_items=[
                    astra.RFQItem(description="item", quantity=100, target_specs="tbd")
                ],
                response_deadline=date(2026, 5, 8),
                attachments_to_include=["NDA-template.pdf", "spec-sheet.pdf"],
            )
        raise AssertionError(f"unhandled output_cls: {output_cls!r}")

    astra._call_structured = fake_call_structured  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Event generation
# --------------------------------------------------------------------------


def _sample_supplier(suppliers: list[dict[str, Any]]) -> dict[str, Any]:
    return random.choice(suppliers)


def _po_total() -> float:
    """Right-skewed PO total: most procurement is routine, a few are big.

    Flat uniform($500, $60k) had mean ~$30k, sending ~58% of POs to Priya
    and starving Marcus's routing buckets. Real procurement is heavy at the
    bottom — bucketed sampling reflects that.
    """
    bucket = random.random()
    if bucket < 0.70:
        return round(random.uniform(500, 5_000), 2)
    if bucket < 0.90:
        return round(random.uniform(5_000, 25_000), 2)
    return round(random.uniform(25_000, 60_000), 2)


def _fake_po(supplier: dict[str, Any], today: date) -> dict[str, Any]:
    total = _po_total()
    return {
        "id": f"PO-{today.strftime('%Y%m%d')}-{random.randint(100, 999)}",
        "total": total,
        "expected_delivery": (
            today + timedelta(days=random.randint(7, 30))
        ).isoformat(),
        "supplier": supplier,
        "line_items": [
            {"sku": "ALU-6061-T6-1IN", "qty": 200, "unit_price": round(total / 200, 2)}
        ],
    }


def _fake_sku(today: date) -> dict[str, Any]:
    return {
        "id": f"SKU-{random.randint(1, 9999):04d}",
        "description": "1in 6061-T6 aluminum bar",
        "unit_cost": round(random.uniform(5, 200), 2),
        "monthly_burn": random.randint(50, 500),
        "reorder_threshold": random.randint(20, 100),
    }


def _fake_invoice(po: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"INV-{po['id'][3:]}",
        "supplier_id": po["supplier"]["id"],
        "lines": [],
    }


def _fake_receipt(po: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"GR-{po['id'][3:]}", "lines": []}


def _fake_supplier_request(today: date) -> dict[str, Any]:
    return {
        "target_supplier_name": random.choice(
            [
                "Pacific Adhesive Solutions",
                "Northbridge Semiconductor",
                "Cascade Steel Mills",
            ]
        ),
        "target_category": random.choice(
            ["adhesives", "electronics", "raw materials", "packaging"]
        ),
        "region": "Pacific Northwest",
        "sourcing_brief": "Structural epoxy for fabrication line.",
        "target_volumes_specs": "500 units/month, ASTM D1002.",
        "acme_contact_name": "Priya Iyer",
        "acme_contact_role": "Senior Buyer",
    }


# --------------------------------------------------------------------------
# Per-event handlers
# --------------------------------------------------------------------------


def _handle_one(
    task_name: str,
    astra_call: Any,
    context: dict[str, Any],
    runtime_url: str,
    counts: Counter[str],
    reviewer_counts: Counter[str],
    correction_counts: Counter[str],
) -> None:
    import vouch
    from reviewers import decide_edit, report_correction, route_reviewer

    counts[task_name] += 1
    try:
        result = astra_call()
    except Exception as exc:
        # An Astra failure still produced a capture (the SDK records errors).
        # We don't route a reviewer for failed drafts.
        print(f"  [error] {task_name}: {exc}", file=sys.stderr)
        return

    capture_id = vouch.get_last_capture_id()
    if capture_id is None:
        return  # SDK failed to set; skip correction step

    output_dict = (
        result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else dict(result)
    )
    reviewer_id = route_reviewer(task_name, context)
    reviewer_counts[reviewer_id] += 1

    decision = decide_edit(task_name, reviewer_id, context, output_dict)
    if decision is None:
        return
    correction_id = report_correction(
        capture_id=capture_id,
        original_output=output_dict,
        edited_output=decision["edited_output"],
        severity=decision["edit_severity"],
        reviewer_id=reviewer_id,
        tags=decision["edit_tags"],
        runtime_url=runtime_url,
    )
    if correction_id:
        correction_counts[reviewer_id] += 1


def _po_ack_event(suppliers: list[dict[str, Any]], today: date, **kw: Any) -> None:
    import astra

    supplier = _sample_supplier(suppliers)
    po = _fake_po(supplier, today)
    fake_email = f"Confirming receipt of {po['id']}. Thanks."
    context = {
        "po_total": po["total"],
        "supplier_tier": supplier["tier"],
    }
    _handle_one(
        "po_acknowledgement",
        lambda: astra.handle_po_ack(fake_email, po),
        context,
        **kw,
    )


def _supplier_followup_event(
    suppliers: list[dict[str, Any]], today: date, **kw: Any
) -> None:
    import astra

    supplier = _sample_supplier(suppliers)
    po = _fake_po(supplier, today)
    days_late = random.randint(1, 21)
    context = {
        "supplier_tier": supplier["tier"],
        "days_late": days_late,
    }
    _handle_one(
        "supplier_followup",
        lambda: astra.draft_supplier_followup(po, days_late, supplier),
        context,
        **kw,
    )


def _invoice_match_event(
    suppliers: list[dict[str, Any]], today: date, **kw: Any
) -> None:
    import astra

    supplier = _sample_supplier(suppliers)
    po = _fake_po(supplier, today)
    receipt = _fake_receipt(po)
    invoice = _fake_invoice(po)
    _handle_one(
        "invoice_three_way_match",
        lambda: astra.reconcile_invoice(po, receipt, invoice),
        {},
        **kw,
    )


def _reorder_event(suppliers: list[dict[str, Any]], today: date, **kw: Any) -> None:
    import astra

    supplier = _sample_supplier(suppliers)
    sku = _fake_sku(today)
    current_stock = random.randint(0, sku["reorder_threshold"])
    # Estimate total cost up front so routing knows whether to send to Priya.
    monthly_burn = sku["monthly_burn"]
    lead = supplier.get("typical_lead_time_days", 14)
    base_qty = monthly_burn * (lead / 30 + 1)
    if supplier.get("reliability", 1.0) < 0.85:
        base_qty *= 1.15
    proposed_qty = -(-int(base_qty) // 10) * 10  # ceil to nearest 10
    estimated_total_cost = round(proposed_qty * sku["unit_cost"], 2)
    context = {
        "estimated_total_cost": estimated_total_cost,
        "lead_time_days": lead,
        "monthly_burn": monthly_burn,
    }
    _handle_one(
        "low_stock_reorder",
        lambda: astra.propose_reorder(sku, current_stock, supplier),
        context,
        **kw,
    )


def _new_supplier_event(
    suppliers: list[dict[str, Any]], today: date, **kw: Any
) -> None:
    import astra

    request = _fake_supplier_request(today)
    _handle_one(
        "new_supplier_engagement",
        lambda: astra.engage_new_supplier(request),
        request,
        **kw,
    )


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------


def _run_day(suppliers: list[dict[str, Any]], today: date, **kw: Any) -> None:
    for _ in range(random.randint(20, 40)):
        _po_ack_event(suppliers, today, **kw)
    for _ in range(random.randint(5, 15)):
        _supplier_followup_event(suppliers, today, **kw)
    for _ in range(random.randint(15, 30)):
        _invoice_match_event(suppliers, today, **kw)
    for _ in range(random.randint(3, 8)):
        _reorder_event(suppliers, today, **kw)
    for _ in range(random.randint(0, 2)):
        _new_supplier_event(suppliers, today, **kw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Acme Industrial simulation runner")
    parser.add_argument("--scenario", default="nominal")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runtime-url", default="http://localhost:8000")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Replace astra._call_structured with a deterministic fake (no LLM calls).",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    os.environ["VOUCH_RUNTIME_URL"] = args.runtime_url

    if args.mock:
        _install_mock_call_structured()

    suppliers = json.loads((_EXAMPLE_DIR / "seed" / "suppliers.json").read_text())

    counts: Counter[str] = Counter()
    reviewer_counts: Counter[str] = Counter()
    correction_counts: Counter[str] = Counter()
    handler_kw = dict(
        runtime_url=args.runtime_url,
        counts=counts,
        reviewer_counts=reviewer_counts,
        correction_counts=correction_counts,
    )

    start = datetime(2026, 4, 1, 0, 0, 0)
    print(
        f"Running scenario={args.scenario} days={args.days} seed={args.seed} "
        f"runtime={args.runtime_url} mock={args.mock}"
    )
    for d in range(args.days):
        today = (start + timedelta(days=d)).date()
        _run_day(suppliers, today, **handler_kw)
        if (d + 1) % 5 == 0 or d == args.days - 1:
            print(
                f"  day {d + 1}/{args.days}: events={sum(counts.values())} corrections={sum(correction_counts.values())}"
            )

    total_events = sum(counts.values())
    total_corrections = sum(correction_counts.values())
    print()
    print("=" * 60)
    print(f"Scenario:       {args.scenario}")
    print(f"Simulated days: {args.days}")
    print(f"Total events:   {total_events}")
    print(f"Total captures: {total_events}  (one per Astra invocation)")
    print(f"Total corrections: {total_corrections}")
    print()
    print("Per-task event counts:")
    for task, n in sorted(counts.items()):
        print(f"  {task:32s} {n:6d}")
    print()
    print("Per-reviewer routing counts:")
    for rev, n in sorted(reviewer_counts.items()):
        edits = correction_counts.get(rev, 0)
        rate = edits / n if n else 0.0
        print(f"  {rev:12s} routed={n:6d}  edits={edits:5d}  rate={rate:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
