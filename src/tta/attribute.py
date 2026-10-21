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

__all__ = ["Attribution", "LogAttribution", "attribute", "attribute_log", "stage_lateness"]

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
    """
    counterfactual = next_departure(shipment.planned_release + handling_seconds, lane)
    return {
        "order_to_release": shipment.released - shipment.planned_release,
        "release_to_depart": shipment.ship_confirm - counterfactual,
        "transit": shipment.stage_durations["transit"] - shipment.committed_transit,
    }


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
    overruns = {stage: max(0, value) for stage, value in raw.items()}
    total_overrun = sum(overruns.values())

    if not shipment.is_late(thresholds.min_lateness_seconds):
        cause = NOT_LATE
        shares: dict[str, float] = {}
    elif total_overrun <= 0:
        # Late, and no stage ran over its plan. The plan did not add up to the
        # promise, which is a planning failure rather than an execution one.
        cause = INFEASIBLE_PLAN
        shares = {}
    elif convention == "first_cause":
        cause = next(stage for stage in STAGES if overruns[stage] > 0)
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
            late_with_multiple_causes=sum(
                1
                for row in late
                if sum(
                    1
                    for value in row.stage_lateness.values()
                    if value > thresholds.min_lateness_seconds
                )
                > 1
            ),
        ),
        rows,
    )
