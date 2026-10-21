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
    upstream, stage, infeasible, precision, multi = [], [], [], [], []
    by_convention = {convention: [] for convention in CONVENTIONS}
    for replication in range(REPLICATIONS):
        seed = 20261021 + 97 * replication
        log, _ = generate_log(SHIPMENTS, seed=seed)
        summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
        upstream.append(summary.upstream_share_of_late)
        stage.append(summary.stage_share_of_late)
        infeasible.append(summary.infeasible_share_of_late)
        precision.append(summary.scorecard_precision)
        multi.append(summary.multiple_cause_share)

        # Three measures this experiment used to publish as separate findings.
        # A late delivery the carrier looks fine on is exactly a late delivery
        # whose cause is upstream, and recall is one minus that, so the three
        # are one measurement and its complement. They were three bullets in
        # the README reading as mutual corroboration. Asserted here rather than
        # reported, so the identity is pinned and the page states it once.
        invisible = summary.late_but_carrier_looks_fine / summary.late
        recall = summary.carrier_flagged_and_truly_carrier / summary.late
        assert invisible == summary.upstream_share_of_late, (
            f"replication {replication}: the invisible share and the upstream share are "
            "the same quantity and have stopped agreeing"
        )
        assert abs(recall - (1 - summary.upstream_share_of_late)) < 1e-12, (
            f"replication {replication}: recall is the complement of the upstream share "
            "and has stopped being it"
        )

        # The headline must not depend on the arbitrary step, so it is measured
        # under every convention on every log. This used to sit outside the
        # replication loop and call `generate_log(SHIPMENTS)` with the default
        # seed three times, so the published convention spread was one draw
        # reported inside a document that opens "twelve independent logs".
        for convention in CONVENTIONS:
            under, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
            by_convention[convention].append(under.upstream_share_of_late)

    spreads = [
        max(values) - min(values)
        for values in zip(*(by_convention[c] for c in CONVENTIONS), strict=True)
    ]

    rows = [
        ("upstream share of late deliveries", upstream),
        ("of which a stage before ship confirm", stage),
        ("of which the plan never reached the promise", infeasible),
        ("scorecard precision, of what it flags", precision),
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
            "upstream_share_by_convention": {
                convention: float(np.mean(values)) for convention, values in by_convention.items()
            },
            "upstream_share_convention_spread": float(np.mean(spreads)),
            "upstream_share_convention_spread_max": float(max(spreads)),
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
