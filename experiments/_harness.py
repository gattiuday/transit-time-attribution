"""Shared plumbing: deterministic setup, JSON output, a printed table."""

from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "experiments"
SHIPMENTS = 4_000
REPLICATIONS = 12

#: Maps each planted cause to the stage an attribution should name where the
#: shipment actually arrived late. The same mapping the grading tests use.
EXPECTED_CAUSE = {
    "warehouse": "order_to_release",
    "missed_cutoff": "release_to_depart",
    "carrier": "transit",
    "infeasible_plan": "infeasible_plan",
    "none": "not_late",
}


def emit(name: str, payload: dict, rows: list[tuple] | None = None, headers=()) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{name}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if rows:
        widths = [
            max(len(str(header)), *(len(str(row[i])) for row in rows))
            for i, header in enumerate(headers)
        ]
        line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths, strict=True))
        print(line)
        print("-" * len(line))
        for row in rows:
            print("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True)))
    print(f"\nwrote {target.relative_to(OUTPUT_DIR.parents[1])}")
