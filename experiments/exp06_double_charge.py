"""What did charging the release overrun twice actually do?

Question this repository has to answer about itself: the first version of
`attribute.py` charged the release overrun once as itself and once as the
departure it pushed, and ADR-007 makes claims about the damage. Those claims are
figures, and a repository whose whole argument is that figures must be measured
cannot except the figures in its own correction notice.

So the defective charge is reconstructed here and run beside the current one.
Everything below is measured from the same logs the other experiments use. The
reconstruction is deliberately a separate function rather than a flag on the
real one, because a module that can still produce the wrong answer on request
will eventually be asked.
"""

from __future__ import annotations

import numpy as np
from _harness import EXPECTED_CAUSE, REPLICATIONS, SHIPMENTS, emit

from tta.attribute import attribute, displacement_residual
from tta.config import next_departure
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.stages import STAGES


def charges_as_first_shipped(shipment, lane, handling_seconds: int) -> dict[str, int]:
    """The decomposition as it was before ADR-007.

    `release_to_depart` is the whole displacement rather than the part the
    release overrun did not force, so an overrun that pushed a departure is
    charged to both stages.
    """
    counterfactual = next_departure(shipment.planned_release + handling_seconds, lane)
    return {
        "order_to_release": shipment.released - shipment.planned_release,
        "release_to_depart": shipment.ship_confirm - counterfactual,
        "transit": shipment.stage_durations["transit"] - shipment.committed_transit,
    }


def cause_under(charges: dict[str, int]) -> str:
    """`largest_cause` over a set of charges, floored the way it was floored then."""
    overruns = {stage: max(0, value) for stage, value in charges.items()}
    if sum(overruns.values()) <= 0:
        return "infeasible_plan"
    return max(STAGES, key=lambda stage: overruns[stage])


def main() -> None:
    lanes = lanes_by_name()
    over_attributed, ratios, old_recovery, new_recovery = [], [], [], []
    warehouse_old, warehouse_new, warehouse_total = 0, 0, 0

    for replication in range(REPLICATIONS):
        log, truth = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
        late = 0
        exceeded = 0
        charged = 0
        actual = 0
        old_correct = 0
        new_correct = 0
        for shipment, planted in zip(log, truth, strict=True):
            lane = lanes[shipment.lane]
            current = attribute(shipment, lane, DEPART_FLOOR_SECONDS, "largest_cause")
            if not current.is_late:
                continue
            late += 1
            old_charges = charges_as_first_shipped(shipment, lane, DEPART_FLOOR_SECONDS)
            positive = sum(max(0, value) for value in old_charges.values())
            if positive > shipment.delivery_lateness + 60:
                exceeded += 1
            charged += positive
            actual += shipment.delivery_lateness

            expected = EXPECTED_CAUSE[planted]
            old_cause = cause_under(old_charges)
            if old_cause == expected:
                old_correct += 1
            if current.cause == expected:
                new_correct += 1
            if planted == "warehouse":
                warehouse_total += 1
                warehouse_old += old_cause == expected
                warehouse_new += current.cause == expected

        for shipment in log:
            assert (
                displacement_residual(shipment, lanes[shipment.lane], DEPART_FLOOR_SECONDS) == 0
            ), shipment.shipment_id
        over_attributed.append(exceeded / late)
        ratios.append(charged / actual)
        old_recovery.append(old_correct / late)
        new_recovery.append(new_correct / late)

    # The invariant the fix rests on, checked inside the replication loop above
    # rather than here. This block ran after the loop and so saw only the last
    # log, while its own comment said "over the same logs", and it asserted the
    # reconciling identity, which an audit showed is zero for every possible
    # input and therefore asserts nothing. `displacement_residual` is the part
    # that can fail and it is asserted per replication.

    rows = [
        ("late deliveries charged past their lateness", over_attributed),
        ("total charged over total lateness", ratios),
        ("recovery under the double charge", old_recovery),
        ("recovery after netting", new_recovery),
    ]
    emit(
        "exp06_double_charge",
        {
            "question": "what did charging the release overrun twice do",
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
            "warehouse_recovered_under_double_charge": warehouse_old,
            "warehouse_recovered_after_netting": warehouse_new,
            "warehouse_planted": warehouse_total,
            "note": (
                "the double charge did not move the headline, which is why it survived: "
                "both upstream stages lie outside the scorecard's window and netting "
                "moves lateness between them rather than out of them. What it moved was "
                "which upstream stage got named, and through that the recovery rate, "
                "which this repository had written up as a structural ceiling on "
                "attribution rather than as its own arithmetic"
            ),
        },
        [
            (
                label,
                f"{np.mean(values):.1%}" if max(values) <= 1 else f"{np.mean(values):.2f}x",
                f"{np.std(values, ddof=1) * 100:.2f}",
            )
            for label, values in rows
        ],
        ("measure", "mean", "sd pts"),
    )


if __name__ == "__main__":
    main()
