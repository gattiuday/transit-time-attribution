"""How large does a sample have to be before any of these rates means anything?

Question the README asks: a scorecard precision in the nineties is a rate over the
shipments it flagged, and on a single lane in a single month that may be a
handful. A rate over a handful is not a rate.

Rule four of this repository's receipts discipline: a measured value is worth
what the sample behind it can resolve. This measures the smallest rate each
sample size can distinguish, and the sample it would take to separate the
measured precision from the claim a transport team would make from it.

The uncomfortable part is at the top of the table. A scorecard that flags four
shipments and is right about all four has a measured precision of 100%, and a
sample that cannot tell that apart from three in four.
"""

from __future__ import annotations

import numpy as np
from _harness import REPLICATIONS, emit

from tta.attribute import attribute_log
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.resolution import rate_with_floor

#: Shipment counts a single lane might contribute to a monthly review.
SAMPLE_SIZES = (250, 500, 1_000, 2_000, 4_000)

#: What a transport team would claim from a high measured precision.
CLAIM = 0.95


def main() -> None:
    rows, series = [], []
    for shipments in SAMPLE_SIZES:
        flagged, precisions, supported = [], [], 0
        for replication in range(REPLICATIONS):
            log, _ = generate_log(shipments, seed=20261021 + 97 * replication)
            summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
            rate = rate_with_floor(
                summary.carrier_flagged_and_truly_carrier, summary.carrier_flagged, CLAIM
            )
            flagged.append(rate.denominator)
            precisions.append(rate.rate)
            supported += int(rate.supported)
        series.append(
            {
                "shipments": shipments,
                "flagged_mean": float(np.mean(flagged)),
                "precision_mean": float(np.mean(precisions)),
                "resolution_floor_mean": float(np.mean([1 / n for n in flagged])),
                "claim_supported_share": supported / REPLICATIONS,
            }
        )
        rows.append(
            (
                shipments,
                f"{np.mean(flagged):.0f}",
                f"{np.mean(precisions):.1%}",
                f"{np.mean([1 / n for n in flagged]):.2%}",
                f"{supported / REPLICATIONS:.0%}",
            )
        )

    smallest_supported = next(
        (row["shipments"] for row in series if row["claim_supported_share"] >= 0.8), None
    )
    emit(
        "exp05_resolution_floor",
        {
            "question": "how large a sample does the scorecard precision claim need",
            "claim": CLAIM,
            "replications": REPLICATIONS,
            "series": series,
            "smallest_sample_supporting_the_claim": smallest_supported,
            "floor_at_smallest_sample": series[0]["resolution_floor_mean"],
            "flagged_at_smallest_sample": series[0]["flagged_mean"],
            "note": (
                "the scorecard flags roughly one shipment in ten, so a lane needs "
                "thousands of shipments before its precision separates from a claim "
                "two points away. A monthly review on one lane is reporting a rate its "
                "sample cannot resolve, and the number looks the same either way"
            ),
        },
        rows,
        ("shipments", "flagged", "precision", "resolution floor", "claim separable"),
    )


if __name__ == "__main__":
    main()
