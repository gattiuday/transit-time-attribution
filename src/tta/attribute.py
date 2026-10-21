"""Attribute a late delivery to the stage that produced it, including unseen ones.

The arithmetic is deliberately simple, because the finding is not in the
arithmetic. For each stage, lateness is the actual duration minus the planned
one. A shipment delivered late had at least one stage that overran, and the
attribution says which.

What makes this worth building is the comparison it enables. A carrier
scorecard computes one of these three numbers and discards the other two, so
it cannot distinguish a carrier that missed its window from a carrier handed a
shipment the warehouse released after the cutoff. Those call for opposite
actions: one is a carrier conversation and one is a warehouse conversation,
and a scorecard answers both with the carrier's name.

Three conventions handle a shipment with more than one late stage, because a
shipment can have several and the split between them is a choice rather than a
measurement. ADR-004.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from tta.config import CONVENTIONS, DEFAULTS, Lane, Thresholds, next_departure
from tta.errors import AttributionError
from tta.stages import CARRIER_STAGE, STAGES, Shipment

__all__ = [
    "Attribution",
    "LogAttribution",
    "admissible_causes",
    "attribute",
    "attribute_log",
    "displacement_residual",
    "promise_slack",
    "residual",
    "stage_lateness",
    "stage_overruns",
]

#: A delivery can be late with no stage overrunning its plan, when the plan
#: itself never added up to the promise. That is a real and common cause, and
#: calling it a stage failure would blame an operation for arithmetic done
#: before it started.
INFEASIBLE_PLAN = "infeasible_plan"
NOT_LATE = "not_late"


def stage_lateness(shipment: Shipment, lane: Lane, handling_seconds: int) -> dict[str, int]:
    """Seconds each stage cost beyond what the plan allowed for it.

    Two of the three are a straight comparison against a plan. The middle one is
    not, and getting it wrong is the easiest mistake in this whole package.

    A shipment waits for a departure whether or not anything went wrong, because
    departures leave on a schedule. Charging the whole wait to the warehouse
    would blame it for the timetable. Charging the wait above some fixed floor
    would blame it for arriving in an unlucky part of the day, which an early
    release can do just as easily as a late one. An earlier version of this
    module did exactly that, and `experiments/exp01` showed it attributing
    shipments whose plan was simply infeasible to a departure wait they had not
    caused.

    So the charge is a counterfactual: the departure this shipment actually
    caught, against the departure it would have caught had it released on plan.
    A release that misses nothing costs nothing here, however long it then
    waits, and a release five minutes late that misses the day's last departure
    costs the entire gap to tomorrow's. That step is the finding. ADR-003.

    The counterfactual gives the displacement, which is not the same as the
    charge. A release that overran by nine hours and thereby pushed the
    departure by a full day accounts for nine of those twenty four hours as
    itself; charging the whole displacement to the departure as well bills the
    same nine hours twice. The first version of this module did that, and an
    audit measured the result: on 88.4% of late deliveries the charges summed
    past the lateness they were explaining, and in total they came to nearly
    twice it. Worse, the double charge was load bearing. A missed departure is
    larger than the overrun that caused it only because the overrun was added
    to it, so `largest_cause` named the departure wait for almost every
    warehouse overrun and the repository wrote that up as a structural ceiling
    on attribution rather than as its own arithmetic. ADR-007.

    So the departure is charged the displacement net of the overrun that forced
    it: the wait that releasing on plan would not have avoided. The three
    charges then satisfy an identity, checked by `residual` below and by a test
    over every shipment in the fixture:

        delivery_lateness = order_to_release
                          + release_to_depart
                          + transit
                          - promise_slack

    where the slack is the buffer the promise holds over the plan. Everything
    this module claims rests on that identity closing, which is why it is
    computed rather than asserted.
    """
    counterfactual = next_departure(shipment.planned_release + handling_seconds, lane)
    order_to_release = shipment.release_lateness
    displacement = shipment.ship_confirm - counterfactual
    return {
        "order_to_release": order_to_release,
        "release_to_depart": displacement - order_to_release,
        "transit": shipment.stage_durations["transit"] - shipment.committed_transit,
    }


def stage_overruns(shipment: Shipment, lane: Lane, handling_seconds: int) -> dict[str, int]:
    """Seconds each stage ran over its plan, which is not the same decomposition.

    `stage_lateness` returns charges that reconcile: they sum to the lateness
    and they carry signs, so a release that beat its plan is a credit. That is
    the right object for checking the arithmetic and the wrong one for naming a
    cause, and the difference is not a detail.

    Consider a release four hours early on a lane with one departure a day. It
    waits four hours longer for the same departure it would have caught anyway,
    so the displacement is zero: the reconciling charges are minus four hours to
    the release and plus four hours to the departure, which sum correctly and
    say something false. The departure did not run over anything. It ran exactly
    to its timetable, and the extra wait is the credit being spent.

    So blame is floored twice rather than once. The departure is over plan only
    if the shipment left later than the departure it would have caught on plan,
    and then only by the part of that displacement the release overrun did not
    force. An early release contributes nothing to either term.
    """
    charges = stage_lateness(shipment, lane, handling_seconds)
    overran = max(0, charges["order_to_release"])
    displacement = charges["order_to_release"] + charges["release_to_depart"]
    return {
        "order_to_release": overran,
        "release_to_depart": max(0, displacement - overran),
        "transit": max(0, charges["transit"]),
    }


def admissible_causes(
    shipment: Shipment,
    lane: Lane,
    handling_seconds: int,
    thresholds: Thresholds = DEFAULTS,
) -> set[str]:
    """Every cause that is true of this shipment, which is usually more than one.

    A planted cause is a label, and a label is a choice among the true
    statements about a shipment. On this generator the choice is close to
    arbitrary for the two upstream causes: a release that overran by nine hours
    has also missed a departure, so `warehouse` and `missed_cutoff` are both
    true of it, and which one was written down depends only on which
    distribution the overrun was drawn from. An audit measured the overlap at
    482 of 484 upstream labels on the committed fixture, and the generator's own
    label verifier passes both, because both are true.

    That makes recovery against a single planted label the wrong question. It
    measures how often the attribution guessed the same true statement the
    generator happened to record, which is not a property of the attribution. It
    is reported anyway, because it is the number every tool in this space
    publishes, but it is reported beside this one: whether the named cause is
    true of the shipment at all. ADR-008.
    """
    overruns = stage_overruns(shipment, lane, handling_seconds)
    material = thresholds.min_lateness_seconds
    causes = {stage for stage, value in overruns.items() if value > material}
    if promise_slack(shipment, lane, handling_seconds) < 0:
        causes.add(INFEASIBLE_PLAN)
    if not shipment.is_late(material):
        causes.add(NOT_LATE)
    return causes


def promise_slack(shipment: Shipment, lane: Lane, handling_seconds: int) -> int:
    """Seconds the promise holds over the plan, which can be negative.

    A plan that departs on schedule and runs the committed transit arrives at
    `counterfactual + committed_transit`. The slack is what the promise allows
    beyond that. It is a declared quantity rather than a measured one: nothing
    in the event log reports it, and it is recovered here by subtraction.

    Negative slack is a promise the plan could never have met, and that is the
    whole of what `infeasible_plan` means. It used to be inferred instead, from
    a delivery being late with no stage over its plan, which is the same set
    only as long as the arithmetic underneath happens to agree. Deriving it
    makes the two statements the same statement.
    """
    counterfactual = next_departure(shipment.planned_release + handling_seconds, lane)
    return shipment.promised_delivery - (counterfactual + shipment.committed_transit)


def residual(shipment: Shipment, lane: Lane, handling_seconds: int) -> int:
    """How far the three charges are from explaining the lateness. Always zero.

    Always zero for every possible input, and that is the point to be honest
    about. The counterfactual departure and the committed transit appear in the
    charges and again in the slack with opposite signs, so they cancel: substitute
    random integers for both and the identity still closes. An audit did exactly
    that and was right to call the earlier framing of this function a tautology
    dressed as a check. ADR-007 claimed it was verified "for every shipment in the
    fixture rather than for an example", and iterating a constant function two
    thousand times verifies nothing.

    What the identity actually buys is narrower and still worth having. Of the
    terms in it, one pairing does not cancel: `order_to_release` and
    `release_to_depart` must sum to the departure displacement. That is the
    constraint the double charge violated, and `displacement_residual` below is
    the half of this that can fail.
    """
    charges = stage_lateness(shipment, lane, handling_seconds)
    slack = promise_slack(shipment, lane, handling_seconds)
    return shipment.delivery_lateness - (sum(charges.values()) - slack)


def displacement_residual(shipment: Shipment, lane: Lane, handling_seconds: int) -> int:
    """How far the two upstream charges are from the departure displacement.

    Unlike `residual` this can be non-zero. The displacement is computed here
    from the timestamps rather than from the charges, so a change to either
    upstream charge that does not preserve their sum shows up: under the double
    charge the two summed to the displacement plus the release overrun, and this
    returned that overrun on every shipment that missed a departure.

    This is the invariant to assert, and `tests/test_attribute.py` asserts it by
    reintroducing the defect and checking the assertion goes red, because an
    invariant that has never been seen to fail is indistinguishable from a
    comment.
    """
    charges = stage_lateness(shipment, lane, handling_seconds)
    counterfactual = next_departure(shipment.planned_release + handling_seconds, lane)
    displacement = shipment.ship_confirm - counterfactual
    return displacement - (charges["order_to_release"] + charges["release_to_depart"])


@dataclass(frozen=True)
class Attribution:
    """One shipment's lateness, and where it came from."""

    shipment_id: str
    lane: str
    delivery_lateness: int
    is_late: bool
    cause: str
    convention: str
    stage_lateness: dict[str, int]
    stage_overruns: dict[str, int]
    shares: dict[str, float]
    carrier_looks_late: bool

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def upstream_of_carrier(self) -> bool:
        """Whether the cause lies outside a carrier scorecard's window."""
        return self.is_late and self.cause not in (CARRIER_STAGE, NOT_LATE)


def attribute(
    shipment: Shipment,
    lane: Lane,
    handling_seconds: int,
    convention: str = "largest_cause",
    thresholds: Thresholds = DEFAULTS,
) -> Attribution:
    """Attribute one shipment.

    `lane` carries the departure schedule and `handling_seconds` the time every
    shipment needs between release and departure. Both are declared operational
    facts from `config`, passed in rather than derived here, so the arithmetic
    in this module holds no knowledge of any particular lane.
    """
    if convention not in CONVENTIONS:
        raise AttributionError(
            f"unknown convention '{convention}'; expected one of {', '.join(CONVENTIONS)}"
        )
    shipment.validate()
    raw = stage_lateness(shipment, lane, handling_seconds)
    overruns = stage_overruns(shipment, lane, handling_seconds)
    # One threshold, used everywhere a stage counts as over plan. Cause
    # selection used `> 0` while the multiple cause count used this, so a stage
    # thirty seconds over plan could be named as the cause of a late delivery
    # and not counted as a second cause of it. The two happened to agree on this
    # fixture, which is why nothing surfaced it.
    material = thresholds.min_lateness_seconds
    total_overrun = sum(value for value in overruns.values() if value > material)

    if not shipment.is_late(thresholds.min_lateness_seconds):
        cause = NOT_LATE
        shares: dict[str, float] = {}
    elif promise_slack(shipment, lane, handling_seconds) < 0:
        # The promise was shorter than the plan it was made against, so this
        # delivery was late before anything happened. Naming a stage would
        # blame an operation for arithmetic done before it started.
        #
        # This used to read `total_overrun <= 0`, which is the same set only
        # while the charges are right. It silently became a catch-all for any
        # shipment the arithmetic failed to explain, which is exactly what a
        # fallback branch should never be.
        cause = INFEASIBLE_PLAN
        shares = {}
    elif total_overrun <= 0:  # pragma: no cover - unreachable while the identity holds
        # Late, with a feasible plan and nothing over plan. The identity in
        # `stage_lateness` makes this impossible: a feasible plan means the
        # delivery arrives by the promise unless some stage ran over, so there
        # is no input that reaches here. It is kept because it was reachable
        # before the identity, when this branch was `total_overrun <= 0` and
        # served as the silent catch-all for anything the arithmetic could not
        # explain. If the decomposition is ever changed so that it can be
        # reached again, this refuses rather than filing the shipment under the
        # nearest available label.
        raise AttributionError(
            f"{shipment.shipment_id} is late by {shipment.delivery_lateness}s with a "
            "feasible plan and no stage over its plan, which the decomposition says "
            "cannot happen. Refusing to name a cause rather than inventing one"
        )
    elif convention == "first_cause":
        cause = next(stage for stage in STAGES if overruns[stage] > material)
        shares = {cause: 1.0}
    elif convention == "largest_cause":
        cause = max(STAGES, key=lambda stage: overruns[stage])
        shares = {cause: 1.0}
    else:
        cause = max(STAGES, key=lambda stage: overruns[stage])
        shares = {stage: overruns[stage] / total_overrun for stage in STAGES if overruns[stage] > 0}

    return Attribution(
        shipment_id=shipment.shipment_id,
        lane=shipment.lane,
        delivery_lateness=shipment.delivery_lateness,
        is_late=shipment.is_late(thresholds.min_lateness_seconds),
        cause=cause,
        convention=convention,
        stage_lateness=raw,
        stage_overruns=overruns,
        shares=shares,
        carrier_looks_late=shipment.carrier_looks_late(thresholds.min_lateness_seconds),
    )


@dataclass(frozen=True)
class LogAttribution:
    """What a whole event log says, beside what a scorecard would have said."""

    shipments: int
    late: int
    causes: dict[str, int]
    convention: str
    carrier_flagged: int
    carrier_flagged_and_truly_carrier: int
    late_but_carrier_looks_fine: int
    late_with_multiple_causes: int

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def on_time_rate(self) -> float:
        return 1.0 - self.late / self.shipments

    @property
    def multiple_cause_share(self) -> float:
        """Share of late deliveries with more than one stage over plan.

        The limit on any single cause attribution, reported rather than worked
        around. A release that overruns by six hours has also missed the day's
        last departure: both stages are over plan, both statements are true, and
        no convention makes one of them the cause. `experiments/exp02` shows
        what that costs each convention.
        """
        if self.late == 0:
            raise AttributionError(
                "no shipment in this log was delivered late, so there is nothing to "
                "attribute and the multiple cause share is undefined rather than zero"
            )
        return self.late_with_multiple_causes / self.late

    @property
    def upstream_share_of_late(self) -> float:
        """Share of late deliveries whose cause a scorecard cannot see.

        The headline. Every one of these is a shipment a carrier scorecard
        either blames the carrier for or misses entirely, and in both cases the
        conversation it prompts is with the wrong party.

        Note what this counts. `infeasible_plan` is in it, and an infeasible
        plan is not a stage: `stage_lateness` above says so, and a promise that
        never reached its own plan has no position relative to a timestamp
        window at all. It belongs in the headline because the question the
        headline answers is what a scorecard cannot see, and a scorecard cannot
        see a planning error either. It does not belong in a sentence that says
        "a stage", which is what the README said until an audit read the two
        definitions side by side. `stage_share_of_late` and
        `infeasible_share_of_late` are the split, so the two can be quoted
        separately and the headline can say what it means.
        """
        if self.late == 0:
            raise AttributionError(
                "no shipment in this log was delivered late, so there is no lateness to "
                "attribute; the upstream share is undefined rather than zero"
            )
        upstream = sum(
            count for cause, count in self.causes.items() if cause not in (CARRIER_STAGE, NOT_LATE)
        )
        return upstream / self.late

    @property
    def stage_share_of_late(self) -> float:
        """Share of late deliveries caused by a stage that ends before ship confirm."""
        if self.late == 0:
            raise AttributionError(
                "no shipment in this log was delivered late, so the stage share is "
                "undefined rather than zero"
            )
        upstream_stages = [stage for stage in STAGES if stage != CARRIER_STAGE]
        return sum(self.causes.get(stage, 0) for stage in upstream_stages) / self.late

    @property
    def infeasible_share_of_late(self) -> float:
        """Share of late deliveries that were late before anything happened."""
        if self.late == 0:
            raise AttributionError(
                "no shipment in this log was delivered late, so the infeasible plan share "
                "is undefined rather than zero"
            )
        return self.causes.get(INFEASIBLE_PLAN, 0) / self.late

    @property
    def scorecard_precision(self) -> float:
        """Of the shipments a scorecard flags, the share the carrier truly caused.

        A measured zero here would be reported with its resolution floor rather
        than as zero, because a rate over a handful of flags says very little.
        `resolution.py` carries that arithmetic.
        """
        if self.carrier_flagged == 0:
            raise AttributionError(
                "the scorecard flagged no shipment, so its precision is undefined rather "
                "than perfect"
            )
        return self.carrier_flagged_and_truly_carrier / self.carrier_flagged


def attribute_log(
    shipments: list[Shipment],
    lanes: dict[str, Lane],
    handling_seconds: int,
    convention: str = "largest_cause",
    thresholds: Thresholds = DEFAULTS,
) -> tuple[LogAttribution, list[Attribution]]:
    """Attribute every shipment in a log and summarise what a scorecard misses."""
    if not shipments:
        raise AttributionError("cannot attribute an empty event log")
    missing = sorted({shipment.lane for shipment in shipments} - set(lanes))
    if missing:
        raise AttributionError(
            f"no lane definition for: {', '.join(missing)}; a departure wait cannot be "
            "judged without the lane's departure schedule"
        )

    rows = [
        attribute(shipment, lanes[shipment.lane], handling_seconds, convention, thresholds)
        for shipment in shipments
    ]
    late = [row for row in rows if row.is_late]
    flagged = [row for row in rows if row.carrier_looks_late]
    return (
        LogAttribution(
            shipments=len(rows),
            late=len(late),
            causes=dict(Counter(row.cause for row in late)),
            convention=convention,
            carrier_flagged=len(flagged),
            carrier_flagged_and_truly_carrier=sum(
                1 for row in flagged if row.is_late and row.cause == CARRIER_STAGE
            ),
            late_but_carrier_looks_fine=sum(1 for row in late if not row.carrier_looks_late),
            # Over `stage_overruns`, not `stage_lateness`. This counted
            # positive entries in the signed decomposition, which is the object
            # `stage_overruns` exists to replace for exactly this purpose: a
            # release four hours early produces a positive departure charge that
            # is the credit being spent, so a pure carrier failure was counted as
            # having more than one stage over plan because the release was nine
            # minutes early. The published share was 87.4% and the quantity it
            # claimed to measure is 61.8%.
            late_with_multiple_causes=sum(
                1
                for row in late
                if sum(
                    1
                    for value in row.stage_overruns.values()
                    if value > thresholds.min_lateness_seconds
                )
                > 1
            ),
        ),
        rows,
    )
