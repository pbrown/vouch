"""Generate 500 supplier profiles for the Acme Industrial simulation.

Calls OpenAI gpt-4o-mini once per category (12 categories, ~40 suppliers each)
with structured outputs, validates each supplier through a Pydantic model,
assigns sequential ids, and writes the result to suppliers.json.

Reads OPENAI_API_KEY from `.env` in the `acme-industrial` directory (or the
environment). Run from repo root or this example:
    cd examples/acme-industrial && uv run python seed/generate_suppliers.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

_EXAMPLE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_EXAMPLE_DIR / ".env")

Tier = Literal["strategic", "preferred", "transactional"]
Currency = Literal["USD", "EUR", "GBP", "CAD", "MXN", "JPY", "CNY"]
PoFormat = Literal["email_pdf", "edi", "portal", "api"]

CATEGORIES: list[str] = [
    "raw materials",
    "fasteners",
    "electronics",
    "packaging",
    "chemicals",
    "adhesives",
    "lubricants",
    "fabricated components",
    "MRO supplies",
    "services",
    "logistics",
    "finished goods resale",
]

TARGET_TOTAL = 500
PER_CATEGORY = 40  # 12 * 40 = 480; the last category gets a top-up to reach 500.

MODEL = "gpt-4o-mini"


class Supplier(BaseModel):
    """Validated supplier profile. `id` is assigned post-generation."""

    name: str = Field(min_length=2, max_length=120)
    category: str
    tier: Tier
    typical_lead_time_days: int = Field(ge=1, le=365)
    reliability: float = Field(ge=0.0, le=1.0)
    communication_style: str = Field(min_length=2, max_length=200)
    currency: Currency
    preferred_po_format: PoFormat
    relationship_years: int = Field(ge=0, le=80)
    notes: str = Field(max_length=400)


class SupplierBatch(BaseModel):
    """Wrapper used as the response schema for structured outputs."""

    suppliers: list[Supplier]


PROMPT_TEMPLATE = """\
You are generating realistic supplier profiles for "Acme Industrial", a fictional
mid-market US manufacturer. Return EXACTLY {n} distinct suppliers in the
category: "{category}". Do not return fewer than {n}. Do not return more.
{variation_hint}

Requirements:
- Names must be realistic for the category. Examples of the right vibe:
  raw materials -> "Cascade Steel Mills", "Pacific Mineral Resources"
  electronics    -> "Cascade Electronics Inc.", "Northbridge Semiconductor"
  packaging      -> "Riverside Corrugated Co.", "Apex Flexible Packaging"
  Avoid generic placeholders like "Widget Corp" or "Supplier 1".
- Tier mix: ~15% strategic, ~30% preferred, ~55% transactional.
- typical_lead_time_days: vary realistically for the category (services and
  logistics can be 1-3 days; fabricated components and electronics often 21-90;
  raw materials 14-60; MRO 2-14).
- reliability: a float in [0.60, 0.99]. Most suppliers should be 0.85-0.97;
  include a small number in the 0.65-0.80 range for color.
- communication_style: short descriptor like "brief, professional",
  "verbose, relationship-driven", "slow but accurate", "responsive, casual".
- currency: mostly USD; include a handful of EUR / GBP / CAD / MXN / JPY / CNY
  where it would be plausible (e.g. European chemicals supplier in EUR).
- preferred_po_format: one of email_pdf, edi, portal, api. Strategic and large
  suppliers lean edi/api; smaller transactional ones lean email_pdf or portal.
- relationship_years: integer 0-40. Strategic skews higher (8-25), transactional
  skews lower (0-6).
- notes: one short sentence with concrete color (contract terms, past quality
  issues, key contact, certifications). Avoid empty notes.

Return strictly valid JSON matching the provided schema. No prose, no markdown.
"""


def generate_for_category(
    client: OpenAI,
    category: str,
    n: int,
    variation_hint: str = "",
) -> list[Supplier]:
    prompt = PROMPT_TEMPLATE.format(
        n=n,
        category=category,
        variation_hint=variation_hint,
    )
    completion = client.beta.chat.completions.parse(
        model=MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You generate realistic structured business data.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format=SupplierBatch,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        print(f"  [warn] no parsed output for {category}", file=sys.stderr)
        return []

    valid: list[Supplier] = []
    for raw in parsed.suppliers:
        try:
            supplier = Supplier.model_validate(
                {**raw.model_dump(), "category": category}
            )
        except ValidationError as exc:
            print(
                f"  [skip] invalid supplier in {category}: {exc.errors()[:1]}",
                file=sys.stderr,
            )
            continue
        valid.append(supplier)
    return valid


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    client = OpenAI()
    out_path = _EXAMPLE_DIR / "seed" / "suppliers.json"

    all_suppliers: list[Supplier] = []
    for idx, category in enumerate(CATEGORIES):
        is_last = idx == len(CATEGORIES) - 1
        already = len(all_suppliers)
        if is_last:
            target = TARGET_TOTAL - already
        else:
            target = PER_CATEGORY
        # Ask for a few extra so validation losses still leave us with target.
        ask = target + 4
        print(f"[{idx + 1:>2}/12] {category}: requesting {ask}...", flush=True)
        batch = generate_for_category(client, category, ask)
        print(f"        got {len(batch)} valid", flush=True)
        # Trim or report short.
        if len(batch) > target:
            batch = batch[:target]
        elif len(batch) < target:
            print(
                f"  [warn] {category} short by {target - len(batch)}; continuing",
                file=sys.stderr,
            )
        all_suppliers.extend(batch)

    # If we ended short of 500, rotate top-up requests across categories with
    # a "round" hint that perturbs the prompt enough to break temperature=0
    # caching from earlier calls. Bail after a few rounds.
    seen_names = {s.name.strip().lower() for s in all_suppliers}
    rotation = list(reversed(CATEGORIES))  # try less-saturated ones first
    round_idx = 0
    while len(all_suppliers) < TARGET_TOTAL and round_idx < 24:
        deficit = TARGET_TOTAL - len(all_suppliers)
        category = rotation[round_idx % len(rotation)]
        ask = min(max(deficit + 2, 6), 20)
        hint = (
            f"This is top-up batch #{round_idx + 1}. Generate suppliers that are "
            f"clearly DIFFERENT in name and region from typical examples in this "
            f"category. Lean toward smaller regional firms and specialist shops."
        )
        print(
            f"[topup r{round_idx + 1}] need {deficit} more; "
            f"asking {ask} in {category}",
            flush=True,
        )
        extra = generate_for_category(client, category, ask, variation_hint=hint)
        added = 0
        for supplier in extra:
            key = supplier.name.strip().lower()
            if key in seen_names:
                continue
            if len(all_suppliers) >= TARGET_TOTAL:
                break
            all_suppliers.append(supplier)
            seen_names.add(key)
            added += 1
        print(f"        added {added} (dedup applied)", flush=True)
        round_idx += 1

    if len(all_suppliers) < TARGET_TOTAL:
        print(
            f"[error] still short: {len(all_suppliers)}/{TARGET_TOTAL}",
            file=sys.stderr,
        )

    # Truncate hard to 500 in case we overshot.
    all_suppliers = all_suppliers[:TARGET_TOTAL]

    # Assign ids sequentially.
    payload = []
    for i, supplier in enumerate(all_suppliers, start=1):
        record = {"id": f"sup-{i:06d}", **supplier.model_dump()}
        payload.append(record)

    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(payload)} suppliers to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
