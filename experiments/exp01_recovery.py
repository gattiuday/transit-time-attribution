"""Does the attribution recover a cause that was planted?

Question the README asks: every number in this repository rests on the claim
that the attribution names the right stage. The event log is generated with the
cause written down, so that claim is checkable rather than asserted, and this
is the confusion matrix.

Replicated across independent logs, because a recovery rate measured once on
one log is one draw.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from _harness import EXPECTED_CAUSE, REPLICATIONS, SHIPMENTS, emit

from tta.attribute import admissible_causes, attribute_log
from tta.config import CONVENTIONS
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name


def main() -> None:
    per_convention, rows = {}, []
    matrices: dict[str, Counter] = {}
    for convention in CONVENTIONS:
        rates, admissible_rates, overlaps = [], [], []
        matrix: Counter = Counter()
        lanes = lanes_by_name()
        for replication in range(REPLICATIONS):
            log, truth = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
            _, attributions = attribute_log(log, lanes, DEPART_FLOOR_SECONDS, convention)
            graded = [
                (shipment, planted, row)
                for shipment, planted, row in zip(log, truth, attributions, strict=True)
                if row.is_late
            ]
            matrix.update((planted, row.cause) for _, planted, row in graded)
            rates.append(
                sum(1 for _, planted, row in graded if EXPECTED_CAUSE[planted] == row.cause)
                / len(graded)
            )
            # Whether the named cause is true of the shipment at all, which is a
            # property of the attribution. Recovery against a single planted
            # label is not: it also measures which of several true statements the
            # generator happened to record. ADR-008.
            admissible_rates.append(
                sum(
                    1
                    for shipment, _, row in graded
                    if row.cause
                    in admissible_causes(shipment, lanes[shipment.lane], DEPART_FLOOR_SECONDS)
                )
                / len(graded)
            )
            # How often the two upstream labels are both true of the same
            # shipment, which is what the gap between the two rates is made of.
            overlaps.append(
                sum(
                    1
                    for shipment, planted, _ in graded
                    if planted in ("warehouse", "missed_cutoff")
                    and {"order_to_release", "release_to_depart"}
                    <= admissible_causes(shipment, lanes[shipment.lane], DEPART_FLOOR_SECONDS)
                )
                / max(
                    1,
                    sum(1 for _, planted, _ in graded if planted in ("warehouse", "missed_cutoff")),
                )
            )
        values = np.array(rates)
        matrices[convention] = matrix
        per_convention[convention] = {
            "recovery_mean": float(values.mean()),
            "recovery_sd": float(values.std(ddof=1)),
            "admissible_mean": float(np.mean(admissible_rates)),
            "admissible_sd": float(np.std(admissible_rates, ddof=1)),
            "upstream_label_overlap_mean": float(np.mean(overlaps)),
            "replications": REPLICATIONS,
            "confusion": {
                f"{planted}->{cause}": count for (planted, cause), count in matrix.items()
            },
        }
        rows.append(
            (
                convention,
                f"{values.mean():.1%}",
                f"{values.std(ddof=1) * 100:.2f}",
                f"{np.mean(admissible_rates):.1%}",
                f"{np.mean(overlaps):.1%}",
            )
        )

    best = max(per_convention.items(), key=lambda item: item[1]["recovery_mean"])
    # Which planted cause each convention loses, which is the real finding:
    # they fail on opposite groups and neither can fix both.
    worst_group = {}
    for convention, matrix in matrices.items():
        misses = Counter(
            planted
            for (planted, cause), count in matrix.items()
            if EXPECTED_CAUSE[planted] != cause
            for _ in range(count)
        )
        worst_group[convention] = misses.most_common(1)[0][0] if misses else None

    emit(
        "exp01_recovery",
        {
            "question": "does the attribution recover the planted cause",
            "shipments_per_log": SHIPMENTS,
            "per_convention": per_convention,
            "best_convention": best[0],
            "best_recovery_mean": best[1]["recovery_mean"],
            "worst_recovery_mean": min(value["recovery_mean"] for value in per_convention.values()),
            "worst_group_per_convention": worst_group,
            "note": (
                "recovery against the planted label and admissibility of the named "
                "cause are two different measurements and only the second is about "
                "the attribution. A release that overran by hours has also missed the "
                "day's last departure, so warehouse and missed_cutoff are both true of "
                "it and which was recorded depends on which distribution the overrun "
                "was drawn from. Every convention names a cause that is true of the "
                "shipment on every late delivery; they differ only in which of the "
                "true causes they name, and recovery measures agreement with the "
                "generator's arbitrary choice rather than correctness"
            ),
        },
        rows,
        ("convention", "recovery", "sd pts", "admissible", "both labels true"),
    )


if __name__ == "__main__":
    main()
