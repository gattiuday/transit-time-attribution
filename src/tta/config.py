"""Thresholds, conventions and lane facts in one place, rather than inline.

Every value here is a judgement call or a declared lane property rather than a
measurement, which is why they are collected: a reviewer who disagrees with one
can see all of them at once and change the one they mean. Nothing here is read
from the environment, so a published figure cannot change because of where it
was run.
"""

from dataclasses import dataclass

#: Attribution conventions for a shipment with more than one late stage.
#: See ADR-004: the choice matters and the tool reports which one produced a
#: number rather than assuming the reader knows.
CONVENTIONS = ("first_cause", "largest_cause", "proportional")

#: Timestamp granularities a transport system might record. The attribution's
#: resolution is bounded by whichever is coarsest. See ADR-002.
GRANULARITIES = {
    "minute": 60,
    "quarter_hour": 900,
    "hour": 3600,
    "day": 86_400,
}


@dataclass(frozen=True)
class Lane:
    """A declared origin to destination lane. None of this is measured.

    cutoff_hour
        Local hour at which the day's last carrier departure leaves. A shipment
        released after it does not leave late by minutes; it waits for the next
        departure. This is the step that a scorecard starting at ship confirm
        cannot see, and ADR-003 explains why it is modelled as a step.
    departures_per_day
        How many chances a shipment has to leave. One means a missed cutoff
        costs a whole day.
    committed_transit_days
        What the carrier contracted to, measured from ship confirm.
    """

    name: str
    cutoff_hour: int
    departures_per_day: int
    committed_transit_days: int


SECONDS_PER_DAY = 86_400


def departure_slots(lane: "Lane") -> list[int]:
    """Second of day at which each of the lane's departures leaves.

    A declared operational fact, not a measurement. One departure means the
    cutoff hour; several are spaced evenly through the working day and ending
    at it.
    """
    if lane.departures_per_day == 1:
        return [lane.cutoff_hour * 3600]
    spacing = (lane.cutoff_hour * 3600) // lane.departures_per_day
    return sorted({spacing * (index + 1) for index in range(lane.departures_per_day)})


def next_departure(ready_at: int, lane: "Lane") -> int:
    """When a shipment ready at `ready_at` actually leaves.

    A shipment ready after the lane's last departure waits for tomorrow's
    first. That step is the quantity a scorecard starting at ship confirm
    cannot see, and it is why minutes of warehouse lateness become a day of
    delivery lateness. ADR-003.
    """
    day, second_of_day = divmod(ready_at, SECONDS_PER_DAY)
    slots = departure_slots(lane)
    for slot in slots:
        if second_of_day <= slot:
            return day * SECONDS_PER_DAY + slot
    return (day + 1) * SECONDS_PER_DAY + slots[0]


#: The lanes in the committed fixture. Chosen so that one has a single daily
#: departure and one has three, because the cost of a missed cutoff is the
#: whole point and it scales inversely with departure frequency.
LANES = (
    Lane("MIDWEST-ONE-DEPART", cutoff_hour=16, departures_per_day=1, committed_transit_days=2),
    Lane("GULF-THREE-DEPART", cutoff_hour=18, departures_per_day=3, committed_transit_days=3),
    Lane("WEST-LONG-HAUL", cutoff_hour=14, departures_per_day=1, committed_transit_days=4),
)


@dataclass(frozen=True)
class Thresholds:
    """Decision thresholds for the CLI verdict.

    min_shipments
        Below this many delivered shipments, no attribution is reported. A
        carrier scorecard built on fewer is a rate with no denominator.
    material_share
        Share of recorded carrier lateness originating upstream above which the
        scorecard is reported as misattributing rather than as roughly right.
    min_lateness_seconds
        A delivery later than promised by less than this is treated as on time.
        Transport systems record arrival to the minute at best and a one second
        miss is a rounding artefact, not a service failure.
    """

    min_shipments: int = 200
    material_share: float = 0.15
    min_lateness_seconds: int = 60


DEFAULTS = Thresholds()
