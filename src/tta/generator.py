"""A seeded event log whose true cause is planted, so the attribution can be graded.

Validating an attribution tool on real transport data is circular: the quantity
you want to check, which stage actually caused a late delivery, is the quantity
the data does not record. That is the whole reason the tool exists. So the log
is generated with the cause written down, and `experiments/exp01` grades the
attribution against it with a confusion matrix.

Each shipment is built by choosing a cause first and then producing timestamps
that realise it:

    none              every stage inside its plan, delivered on time
    warehouse         the release runs over its planned time
    missed_cutoff     the release is only slightly late, but late enough to
                      miss the lane's last departure, so the shipment waits for
                      the next one. This is the case a scorecard is blind to by
                      construction: the carrier then gets a fresh full window
                      and makes it comfortably
    carrier           the transit exceeds the committed window
    infeasible_plan   every stage inside its plan and the plan never added up
                      to the promise

`missed_cutoff` and `warehouse` are both upstream of ship confirm and are kept
apart because they behave differently: one is proportional to the overrun and
the other is a step. A tool that lumped them would report the right total and
the wrong fix.
"""

from __future__ import annotations

import numpy as np

from tta.config import LANES, Lane, next_departure
from tta.errors import AttributionError
from tta.stages import SECONDS_PER_DAY, Shipment

CAUSES = ("none", "warehouse", "missed_cutoff", "carrier", "infeasible_plan")

#: Share of shipments generated with each planted cause. Late shipments are
#: over represented relative to a healthy operation on purpose: a log with two
#: percent lateness supports no attribution at all, and the resolution
#: experiment measures exactly that limit rather than hiding behind it.
CAUSE_MIX = {
    "none": 0.62,
    "warehouse": 0.12,
    "missed_cutoff": 0.13,
    "carrier": 0.10,
    "infeasible_plan": 0.03,
}

#: Handling time between a release and the departure it makes, in seconds. Every
#: shipment pays it, so the attribution subtracts it before judging the wait.
DEPART_FLOOR_SECONDS = 2 * 3600

#: Planned warehouse time from order to release.
PLANNED_RELEASE_SECONDS = 6 * 3600


def lanes_by_name() -> dict[str, Lane]:
    """The fixture's lanes, keyed for the attribution."""
    return {lane.name: lane for lane in LANES}


def generate_log(
    shipments: int = 2_000, seed: int = 20261021, cause_mix: dict[str, float] | None = None
) -> tuple[list[Shipment], list[str]]:
    """Generate an event log and the planted cause of each shipment.

    Returns the shipments and a parallel list of causes. The causes are the
    ground truth and are never written into the shipment itself, so nothing
    downstream can read the answer by accident.
    """
    if shipments < 1:
        raise AttributionError(f"shipments must be at least 1, got {shipments}")
    mix = cause_mix or CAUSE_MIX
    if abs(sum(mix.values()) - 1.0) > 1e-9:
        raise AttributionError(f"cause mix must sum to 1, got {sum(mix.values())}")
    unknown = sorted(set(mix) - set(CAUSES))
    if unknown:
        raise AttributionError(f"unknown cause(s) in mix: {', '.join(unknown)}")

    rng = np.random.default_rng(seed)
    names = list(mix)
    weights = np.array([mix[name] for name in names], dtype=float)
    planted = rng.choice(names, size=shipments, p=weights / weights.sum())

    log: list[Shipment] = []
    for index, cause in enumerate(planted):
        lane = LANES[index % len(LANES)]
        # Orders are created through the working day, well before the cutoff,
        # so a shipment that releases on plan comfortably makes its departure.
        day = int(index // 3)
        created_hour = float(rng.uniform(1.0, 6.0))
        order_created = day * SECONDS_PER_DAY + int(created_hour * 3600)
        planned_release = order_created + PLANNED_RELEASE_SECONDS

        if cause == "warehouse":
            # A substantial overrun: hours, not minutes. Large enough that the
            # release lateness itself is the story.
            overrun = int(rng.uniform(6.0, 20.0) * 3600)
        elif cause == "missed_cutoff":
            # Just enough to miss the departure an on plan release would have
            # caught. Minutes.
            #
            # The bound here was `next_departure(planned_release, lane)`, which
            # omits the handling floor and so names a departure the shipment was
            # never going to catch. Where the lane's departures are spaced more
            # closely than the floor, that bound fell below the planned release,
            # the overrun went negative, and `max(60, ...)` clamped it to a
            # minute: a shipment released one minute late, missing nothing, and
            # labelled `missed_cutoff`. It affected 35 of 272 such labels on the
            # committed fixture, all on the three departure lane, and the
            # grading test that should have caught it filtered them out because
            # they were not late. The clamp is gone with the bug, because a
            # clamp that silently rescues an impossible value is how the label
            # stayed false through two label audits.
            latest_in_time = (
                next_departure(planned_release + DEPART_FLOOR_SECONDS, lane) - DEPART_FLOOR_SECONDS
            )
            overrun = latest_in_time - planned_release + int(rng.uniform(60, 2_400))
        elif cause == "infeasible_plan":
            # Must not overrun any stage: the planted cause is that the plan
            # itself never reached the promise. Releasing a little early
            # guarantees the shipment makes its planned departure, so no stage
            # can be charged and the attribution has to reach for the plan.
            # Without this the generator produced shipments labelled
            # infeasible_plan whose departure wait had in fact overrun, and the
            # confusion matrix in exp01 showed them as misattributions when the
            # label was the thing that was wrong.
            overrun = -int(rng.uniform(600, 3_600))
        else:
            # `none` and `carrier` must not overrun the warehouse stage, or the
            # planted label is false: a "none" shipment that drifts past the
            # cutoff really did miss it, and counting that as a misattribution
            # grades the generator rather than the attribution. Releasing on or
            # slightly before plan keeps the label true.
            overrun = -int(rng.uniform(0, 1_800))
        released = planned_release + overrun

        ship_confirm = next_departure(released + DEPART_FLOOR_SECONDS, lane)
        committed_transit = lane.committed_transit_days * SECONDS_PER_DAY

        if cause == "carrier":
            transit = committed_transit + int(rng.uniform(0.3, 1.8) * SECONDS_PER_DAY)
        else:
            transit = committed_transit - int(abs(rng.normal(0, 3_600)))
        delivered = ship_confirm + transit

        # The promise: what the customer was told when the order was taken.
        # Built from the plan, with slack, so an on plan shipment lands early.
        promise_slack = int(rng.uniform(0.2, 0.6) * SECONDS_PER_DAY)
        on_plan_depart = next_departure(planned_release + DEPART_FLOOR_SECONDS, lane)
        promised_delivery = on_plan_depart + committed_transit + promise_slack
        if cause == "infeasible_plan":
            # The promise was never achievable from the plan itself: it is set
            # before even an on plan shipment could arrive. No stage overruns.
            promised_delivery = (
                on_plan_depart + committed_transit - int(rng.uniform(0.2, 0.8) * SECONDS_PER_DAY)
            )

        log.append(
            Shipment(
                shipment_id=f"SHP-{index:06d}",
                lane=lane.name,
                order_created=order_created,
                released=released,
                ship_confirm=ship_confirm,
                delivered=delivered,
                promised_delivery=promised_delivery,
                planned_release=planned_release,
                committed_transit=committed_transit,
            ).validate()
        )
    causes = [str(cause) for cause in planted]
    verify_labels(log, causes)
    return log, causes


def label_is_true(shipment: Shipment, cause: str) -> str | None:
    """Why `cause` is false for `shipment`, or None if it holds.

    Three planted labels in this generator have been wrong, each found by a
    confusion matrix rather than by a test, and each time the tool was right
    and the label was not. A grader cannot be trusted further than the ground
    truth it grades against, so the ground truth is checked here against the
    event log it produced, every time one is produced.

    What each label asserts is narrower than it looks, and getting that wrong in
    either direction plants a false label. An execution label names a stage that
    ran over its plan. It does not claim the delivery was late, because the
    promise carries a buffer and a lane with three departures a day absorbs a
    good deal: the first version of this check demanded lateness of `warehouse`
    and `carrier` and found 26 shipments that overran and arrived on time. Those
    labels are true and the absorption is Claim 2's finding, not a defect.

    `infeasible_plan` is about the plan and not the outcome either, for the same
    reason: it asserts the promise was shorter than the plan it was made
    against, and execution can still beat a plan by enough to land on time. One
    shipment in four thousand does, by catching an earlier departure than the
    plan assumed and running under the committed transit. Demanding lateness
    here would have meant widening the generator's infeasibility margin until
    the label came true, which is tuning the ground truth to fit the check.

    `none` is the one label that constrains the outcome, because it is the one
    that claims nothing happened: nothing ran over and the delivery was on time.
    A `none` shipment that drifted past a cutoff really did miss it.
    """
    lane = lanes_by_name()[shipment.lane]
    on_plan_depart = next_departure(shipment.planned_release + DEPART_FLOOR_SECONDS, lane)
    released_over = shipment.released > shipment.planned_release
    missed = shipment.ship_confirm > on_plan_depart
    transit_over = shipment.stage_durations["transit"] > shipment.committed_transit
    feasible = shipment.promised_delivery >= on_plan_depart + shipment.committed_transit
    late = shipment.delivery_lateness > 60

    if cause == "none":
        if released_over or missed or transit_over:
            return "a stage ran over its plan"
        if late:
            return "delivered late"
    elif cause == "warehouse":
        if not released_over:
            return "the release did not overrun"
    elif cause == "missed_cutoff":
        if not released_over:
            return "the release did not overrun"
        if not missed:
            return "no departure was missed"
    elif cause == "carrier":
        if not transit_over:
            return "the transit did not overrun"
        if released_over or missed:
            return "an upstream stage ran over its plan too"
    elif cause == "infeasible_plan":
        if feasible:
            return "the plan did reach the promise"
        if released_over or missed or transit_over:
            return "a stage ran over its plan"
    else:  # pragma: no cover - guarded by the cause mix validation above
        return f"unknown cause '{cause}'"
    return None


def verify_labels(log: list[Shipment], causes: list[str]) -> None:
    """Refuse to hand back a log whose own ground truth is false."""
    wrong = [
        (shipment.shipment_id, cause, reason)
        for shipment, cause in zip(log, causes, strict=True)
        if (reason := label_is_true(shipment, cause)) is not None
    ]
    if wrong:
        shown = "; ".join(f"{name} labelled {cause}: {reason}" for name, cause, reason in wrong[:5])
        raise AttributionError(
            f"{len(wrong)} of {len(log)} planted labels are false, so this log cannot "
            f"grade anything. {shown}"
        )
