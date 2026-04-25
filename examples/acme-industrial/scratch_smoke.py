"""Live smoke for the non-PO-ack prompts.

Each scenario hand-picks a supplier (or builds one) and constructs an input
that exercises an interesting branch of the corresponding prompt. The output
is for eyeballing, not asserting — run, read, and look for prompt-design
issues that the mocked tests can't catch.

    uv run python scratch_smoke.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import astra

_SEED = Path(__file__).parent / "seed" / "suppliers.json"
SUPPLIERS: list[dict[str, Any]] = json.loads(_SEED.read_text())


def pick_supplier(tier: str, category: str | None = None) -> dict[str, Any]:
    for s in SUPPLIERS:
        if s["tier"] == tier and (category is None or s["category"] == category):
            return s
    raise RuntimeError(f"no supplier with tier={tier} category={category}")


def header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def smoke_followup_strategic_urgent() -> None:
    supplier = pick_supplier("strategic")
    po = {
        "id": "PO-2026-03017",
        "total": 28500.00,
        "expected_delivery": "2026-04-15",
    }
    header(
        f"supplier_followup — {supplier['name']} (strategic, "
        f"{supplier['relationship_years']}yr), 10 days late, $28.5K"
    )
    out = astra.draft_supplier_followup(po=po, days_late=10, supplier=supplier)
    print(out.model_dump_json(indent=2))


def smoke_followup_transactional_soft() -> None:
    supplier = pick_supplier("transactional")
    po = {
        "id": "PO-2026-04031",
        "total": 1850.00,
        "expected_delivery": "2026-04-23",
    }
    header(
        f"supplier_followup — {supplier['name']} (transactional, "
        f"{supplier['relationship_years']}yr), 2 days late, $1.85K"
    )
    out = astra.draft_supplier_followup(po=po, days_late=2, supplier=supplier)
    print(out.model_dump_json(indent=2))


def smoke_invoice_discrepancy() -> None:
    po = {
        "id": "PO-2026-04007",
        "supplier_id": "sup-000042",
        "total": 6950.00,
        "lines": [
            {"line_no": 1, "sku": "FAS-M8X25-SS", "qty": 5000, "unit_price": 0.85},
            {"line_no": 2, "sku": "FAS-M10X40-SS", "qty": 2000, "unit_price": 1.35},
        ],
    }
    receipt = {
        "id": "GR-2026-04007",
        "po_id": "PO-2026-04007",
        "lines": [
            {"line_no": 1, "sku": "FAS-M8X25-SS", "qty_received": 5000},
            {"line_no": 2, "sku": "FAS-M10X40-SS", "qty_received": 2000},
        ],
    }
    invoice = {
        "id": "INV-77821",
        "supplier_id": "sup-000042",
        "po_id": "PO-2026-04007",
        "total": 7350.00,  # $400 over PO
        "lines": [
            {"line_no": 1, "sku": "FAS-M8X25-SS", "qty": 5000, "unit_price": 0.85},
            {"line_no": 2, "sku": "FAS-M10X40-SS", "qty": 2000, "unit_price": 1.55},
        ],
    }
    header("invoice_three_way_match — line 2 unit price $1.35 -> $1.55 (+$0.20)")
    out = astra.reconcile_invoice(po=po, receipt=receipt, invoice=invoice)
    print(out.model_dump_json(indent=2))


def smoke_invoice_clean() -> None:
    po = {
        "id": "PO-2026-04019",
        "supplier_id": "sup-000003",
        "total": 5400.00,
        "lines": [
            {"line_no": 1, "sku": "ALU-6061-T6-1IN", "qty": 200, "unit_price": 27.00},
        ],
    }
    receipt = {
        "id": "GR-2026-04019",
        "po_id": "PO-2026-04019",
        "lines": [{"line_no": 1, "sku": "ALU-6061-T6-1IN", "qty_received": 200}],
    }
    invoice = {
        "id": "INV-99014",
        "supplier_id": "sup-000003",
        "po_id": "PO-2026-04019",
        "total": 5400.00,
        "lines": [
            {"line_no": 1, "sku": "ALU-6061-T6-1IN", "qty": 200, "unit_price": 27.00},
        ],
    }
    header("invoice_three_way_match — clean match, expect approve")
    out = astra.reconcile_invoice(po=po, receipt=receipt, invoice=invoice)
    print(out.model_dump_json(indent=2))


def smoke_reorder_capex() -> None:
    supplier = pick_supplier("preferred", "electronics")
    sku = {
        "id": "ELC-PCB-Z47",
        "description": "4-layer PCB, controller board, RoHS",
        "unit_cost": 18.50,
        "monthly_burn": 800,
        "reorder_threshold": 200,
    }
    header(
        f"low_stock_reorder — {sku['id']}, capex territory "
        f"(800/mo @ $18.50, lead {supplier['typical_lead_time_days']}d)"
    )
    out = astra.propose_reorder(sku=sku, current_stock=180, supplier=supplier)
    print(out.model_dump_json(indent=2))


def smoke_reorder_routine() -> None:
    supplier = pick_supplier("transactional", "MRO supplies")
    sku = {
        "id": "MRO-NITRILE-GLV-L",
        "description": "Nitrile gloves, large, box of 100",
        "unit_cost": 12.00,
        "monthly_burn": 40,
        "reorder_threshold": 30,
    }
    header(
        f"low_stock_reorder — {sku['id']}, routine "
        f"(40/mo @ $12, lead {supplier['typical_lead_time_days']}d)"
    )
    out = astra.propose_reorder(sku=sku, current_stock=25, supplier=supplier)
    print(out.model_dump_json(indent=2))


def smoke_engagement() -> None:
    supplier_request = {
        "target_supplier_name": "Northbridge Adhesive Systems",
        "target_category": "adhesives",
        "region": "Pacific Northwest",
        "sourcing_brief": (
            "Acme is sole-sourced on structural epoxy for the aluminum frame "
            "line and wants a qualified backup supplier."
        ),
        "target_volumes_specs": (
            "~500 kg/month, ASTM D1002 lap shear >= 3000 psi, "
            "operating temp range -40C to +120C."
        ),
        "acme_contact_name": "Priya Iyer",
        "acme_contact_role": "Senior Buyer",
    }
    header("new_supplier_engagement — adhesives, second-source RFQ")
    out = astra.engage_new_supplier(supplier_request=supplier_request)
    print(out.model_dump_json(indent=2))


if __name__ == "__main__":
    smoke_followup_strategic_urgent()
    smoke_followup_transactional_soft()
    smoke_invoice_discrepancy()
    smoke_invoice_clean()
    smoke_reorder_capex()
    smoke_reorder_routine()
    smoke_engagement()
