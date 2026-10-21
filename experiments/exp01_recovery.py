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

from tta.attribute import attribute_log
from tta.config import CONVENTIONS
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name


def main() -> None:
    per_convention, rows = {}, []
    matrices: dict[str, Counter] = {}
    for convention in CONVENTIONS:
        rates = []
        matrix: Counter = Counter()
        for replication in range(REPLICATIONS):
            log, truth = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
            _, attributions = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
            graded = [
                (planted, row)
                for planted, row in zip(truth, attributions, strict=True)
                if row.is_late
            ]
            matrix.update((planted, row.cause) for planted, row in graded)
            rates.append(
                sum(1 for planted, row in graded if EXPECTED_CAUSE[planted] == row.cause)
                / len(graded)
            )
        values = np.array(rates)
        matrices[convention] = matrix
        per_convention[convention] = {
            "recovery_mean": float(values.mean()),
            "recovery_sd": float(values.std(ddof=1)),
            "replications": REPLICATIONS,
            "confusion": {
                f"{planted}->{cause}": count for (planted, cause), count in matrix.items()
            },
        }
        rows.append(
            (
                convention,
                f"{values.mean():.4f}",
                f"{values.std(ddof=1) * 100:.2f}",
                f"{values.min():.4f}",
                f"{values.max():.4f}",
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
                "no convention clears four fifths, and the two single cause ones fail "
                "on opposite groups. That is not a defect in the arithmetic: a release "
                "that overran by hours has also missed the day's last departure, both "
                "stages are over plan, and no rule makes one of them the cause"
            ),
        },
        rows,
        ("convention", "recovery mean", "sd pts", "min", "max"),
    )


if __name__ == "__main__":
    main()
