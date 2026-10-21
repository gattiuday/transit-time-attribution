"""What timestamp granularity costs an attribution, and the floor under every rate.

Two separate limits, both easy to leave out of a report and both capable of
reversing a conclusion.

The first is granularity. A transport system that records milestones to the
hour cannot see a release that missed a 16:00 cutoff by six minutes: rounded to
the hour it either made the cutoff or missed it by an hour, and which of those
appears depends on the rounding rule rather than on what happened. Every
attribution that depends on a near miss is lost at that granularity, and the
share lost is measurable rather than arguable.

The second is the resolution floor under a measured rate. A scorecard precision
of 100% over eleven flagged shipments is not 100%: it is "above eight in nine",
and the sample size needed to support the claim being made from it is
arithmetic. A measured zero gets the same treatment: zero misattributions over
forty flags is "below one in forty", not none.
"""

from __future__ import annotations

from dataclasses import dataclass

from tta.config import GRANULARITIES
from tta.errors import AttributionError
from tta.stages import Shipment

__all__ = ["RateWithFloor", "coarsen", "rate_with_floor"]


def coarsen(shipment: Shipment, granularity: str, mode: str = "floor") -> Shipment:
    """Round a shipment's timestamps to a coarser granularity.

    `mode` decides the rounding and it is a parameter because the choice is not
    neutral: flooring every milestone moves a release earlier, which hides a
    near miss, while rounding to nearest moves half of them later, which
    invents one. A system that records to the hour has made this choice
    already, usually without recording which. ADR-002.
    """
    if granularity not in GRANULARITIES:
        raise AttributionError(
            f"unknown granularity '{granularity}'; expected one of {', '.join(GRANULARITIES)}"
        )
    if mode not in ("floor", "nearest"):
        raise AttributionError(f"unknown rounding mode '{mode}'; expected floor or nearest")
    step = GRANULARITIES[granularity]

    def round_to(value: int) -> int:
        if mode == "floor":
            return value - value % step
        return int(round(value / step) * step)

    return Shipment(
        shipment_id=shipment.shipment_id,
        lane=shipment.lane,
        order_created=round_to(shipment.order_created),
        released=round_to(shipment.released),
        ship_confirm=round_to(shipment.ship_confirm),
        delivered=round_to(shipment.delivered),
        promised_delivery=round_to(shipment.promised_delivery),
        planned_release=round_to(shipment.planned_release),
        committed_transit=shipment.committed_transit,
    )


@dataclass(frozen=True)
class RateWithFloor:
    """A measured rate, its resolution floor, and what it would take to support it."""

    numerator: int
    denominator: int
    claim: float

    @property
    def rate(self) -> float:
        if self.denominator == 0:
            raise AttributionError("a rate over zero observations is undefined, not zero")
        return self.numerator / self.denominator

    @property
    def floor(self) -> float:
        """One over the sample size: the smallest rate this sample can distinguish."""
        if self.denominator == 0:
            raise AttributionError("a resolution floor over zero observations is undefined")
        return 1.0 / self.denominator

    @property
    def supported(self) -> bool:
        """Whether the sample can tell the measured rate from the claimed one.

        A rate measured at 100% and claimed at 95% is supported only if the
        sample is large enough that a 5 point shortfall would have shown up.
        """
        return abs(self.rate - self.claim) > self.floor

    def samples_needed(self) -> int:
        """How many observations the claim would need to be distinguishable.

        Reported even when the claim is already supported, because a reader
        comparing two lanes needs to know which of them is resolving anything.
        """
        gap = abs(self.rate - self.claim)
        if gap <= 0:
            raise AttributionError(
                "a rate exactly equal to the claim needs an infinite sample to separate "
                "them; there is nothing to resolve"
            )
        return int(1.0 / gap) + 1


def rate_with_floor(numerator: int, denominator: int, claim: float) -> RateWithFloor:
    if denominator < 0 or numerator < 0:
        raise AttributionError("a rate cannot be built from negative counts")
    if numerator > denominator:
        raise AttributionError(
            f"numerator {numerator} exceeds denominator {denominator}; this is not a rate"
        )
    return RateWithFloor(numerator, denominator, claim)
