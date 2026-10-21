"""How large does a sample have to be before any of these rates means anything?

Question the README asks: a scorecard precision in the nineties is a rate over the
shipments it flagged, and on a single lane in a single month that may be a
handful. A rate over a handful is not a rate.

Rule four of this repository's receipts discipline: a measured value is worth
what the sample behind it can resolve. This measures the smallest rate each
sample size can distinguish, and the sample it would take to separate the
measured precision from the claim a transport team would make from it.

The uncomfortable part is at the top of the table. A scorecard that flags four
shipments and is right about all four has a perfect measured precision, and a
sample that cannot tell that apart from three in four.
"""

from __future__ import annotations

import numpy as np
from _harness import REPLICATIONS, emit

from tta.attribute import attribute_log
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.resolution import rate_with_floor

#: Shipment counts a single lane might contribute to a monthly review, extended
#: upward because the honest interval is not cleared anywhere in the original
#: range. The first three are the realistic ones; the rest are what it would
#: actually take.
SAMPLE_SIZES = (250, 500, 1_000, 2_000, 4_000, 8_000, 16_000, 32_000)

#: What a transport team would claim from a high measured precision.
CLAIM = 0.95


def main() -> None:
    rows, series, needed_by_size = [], [], {}
    for shipments in SAMPLE_SIZES:
        flagged, precisions, resolutions, needed, supported = [], [], [], [], 0
        for replication in range(REPLICATIONS):
            log, _ = generate_log(shipments, seed=20261021 + 97 * replication)
            summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
            rate = rate_with_floor(
                summary.carrier_flagged_and_truly_carrier, summary.carrier_flagged, CLAIM
            )
            flagged.append(rate.denominator)
            precisions.append(rate.rate)
            resolutions.append(rate.resolution)
            needed.append(rate.samples_needed())
            supported += int(rate.supported)
        needed_by_size[shipments] = list(needed)
        series.append(
            {
                "shipments": shipments,
                "flagged_mean": float(np.mean(flagged)),
                "precision_mean": float(np.mean(precisions)),
                "resolution_floor_mean": float(np.mean([1 / n for n in flagged])),
                "resolution_mean": float(np.mean(resolutions)),
                "claim_supported_share": supported / REPLICATIONS,
            }
        )
        rows.append(
            (
                shipments,
                f"{np.mean(flagged):.0f}",
                f"{np.mean(precisions):.1%}",
                f"{np.mean([1 / n for n in flagged]):.2%}",
                f"{np.mean(resolutions):.2%}",
                f"{supported / REPLICATIONS:.0%}",
            )
        )

    # The smallest size from which the claim is supported and stays supported.
    # Taking the first crossing of a noisy share was the previous answer and it
    # landed on a 12 of 12 immediately followed by an 11 of 12, which is one log
    # of difference published as a threshold.
    smallest_supported = None
    for index, row in enumerate(series):
        if all(later["claim_supported_share"] >= 0.8 for later in series[index:]):
            smallest_supported = row["shipments"]
            break

    # What the arithmetic says at the sample a transport team actually has.
    # This read `needed`, which is rebound at the top of every outer iteration,
    # so the published figure was the median over the 32,000 shipment runs: some
    # three thousand flags each, which is not a sample anyone reviewing one lane
    # for a month is holding. The smallest swept size is, and it is the size the
    # sentence around this figure is about.
    flags_needed = int(np.median(needed_by_size[SAMPLE_SIZES[0]]))
    emit(
        "exp05_resolution_floor",
        {
            "question": "how large a sample does the scorecard precision claim need",
            "claim": CLAIM,
            "replications": REPLICATIONS,
            "series": series,
            "smallest_sample_supporting_the_claim": smallest_supported,
            "flags_needed_to_separate_the_claim": flags_needed,
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
        ("shipments", "flagged", "precision", "granularity", "resolution", "claim separable"),
    )


if __name__ == "__main__":
    main()
