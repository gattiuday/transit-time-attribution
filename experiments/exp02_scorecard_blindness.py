"""How much of the lateness does a carrier scorecard not see, and is it precise?

Question the README asks: a carrier on time in full scorecard starts at ship
confirm. What share of late deliveries has a cause before that moment, how many
of those does the scorecard record as a carrier success, and how often is it
right about the ones it does flag?

The last of those is the uncomfortable one. A scorecard that flagged randomly
would be easy to distrust. One that is nearly always right about what it flags,
and sees a quarter of the problem, reads as trustworthy.
"""

from __future__ import annotations

import numpy as np
from _harness import REPLICATIONS, SHIPMENTS, emit

from tta.attribute import attribute_log
from tta.config import CONVENTIONS
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name


def main() -> None:
    upstream, precision, recall, invisible, multi = [], [], [], [], []
    by_convention = {}
    for replication in range(REPLICATIONS):
        log, _ = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
        summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
        upstream.append(summary.upstream_share_of_late)
        precision.append(summary.scorecard_precision)
        recall.append(summary.carrier_flagged_and_truly_carrier / summary.late)
        invisible.append(summary.late_but_carrier_looks_fine / summary.late)
        multi.append(summary.multiple_cause_share)

    # The headline must not depend on the arbitrary step, so it is measured
    # under every convention rather than asserted to be independent.
    for convention in CONVENTIONS:
        log, _ = generate_log(SHIPMENTS)
        summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
        by_convention[convention] = summary.upstream_share_of_late

    rows = [
        ("upstream share of late deliveries", upstream),
        ("scorecard precision, of what it flags", precision),
        ("scorecard recall, of all late deliveries", recall),
        ("late with the carrier inside its window", invisible),
        ("late with more than one stage over plan", multi),
    ]
    printed = [
        (
            label,
            f"{np.mean(values):.1%}",
            f"{np.std(values, ddof=1) * 100:.2f}",
            f"{min(values):.1%}",
            f"{max(values):.1%}",
        )
        for label, values in rows
    ]

    emit(
        "exp02_scorecard_blindness",
        {
            "question": "how much of the lateness can a carrier scorecard not see",
            "replications": REPLICATIONS,
            "shipments_per_log": SHIPMENTS,
            "measures": {
                label: {
                    "mean": float(np.mean(values)),
                    "sd": float(np.std(values, ddof=1)),
                    "min": float(min(values)),
                    "max": float(max(values)),
                }
                for label, values in rows
            },
            "upstream_share_by_convention": by_convention,
            "upstream_share_convention_spread": max(by_convention.values())
            - min(by_convention.values()),
            "note": (
                "the upstream share is identical under every convention, because both "
                "upstream stages lie outside the scorecard's window and which of them "
                "is named cannot change how much it misses. Precision and recall are "
                "the pair that matters: the scorecard is right about what it flags and "
                "flags a minority of what went wrong"
            ),
        },
        printed,
        ("measure", "mean", "sd pts", "min", "max"),
    )


if __name__ == "__main__":
    main()
