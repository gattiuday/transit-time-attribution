"""What timestamp granularity costs an attribution, and the floor under every rate.

Two separate limits, both easy to leave out of a report and both capable of
reversing a conclusion.

The first is granularity. A transport system that records milestones to the
hour cannot see a release that missed a 16:00 cutoff by six minutes: rounded to
the hour it either made the cutoff or missed it by an hour, and which of those
appears depends on the rounding rule rather than on what happened. Every
attribution that depends on a near miss is lost at that granularity, and the
share lost is measurable rather than arguable.

The second is the resolution floor under a measured rate. A perfect scorecard
precision over eleven flagged shipments is not perfection: it is "above eight in
nine", and the sample size needed to support the claim being made from it is
arithmetic. A measured zero gets the same treatment: zero misattributions over
forty flags is "below one in forty", not none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

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

    #: Where `samples_needed` gives up. A transport team comparing lanes over a
    #: month is not going to reach this, and an unbounded search on a gap of a
    #: few thousandths would not terminate in useful time.
    MAX_SAMPLE: ClassVar[int] = 200_000

    @property
    def rate(self) -> float:
        if self.denominator == 0:
            raise AttributionError("a rate over zero observations is undefined, not zero")
        return self.numerator / self.denominator

    @property
    def floor(self) -> float:
        """One over the sample size: the smallest difference this rate can express.

        This is a statement about granularity and nothing else. A rate over n
        observations can only take the values k/n, so a difference below 1/n
        cannot be represented, let alone measured.

        It is not a confidence interval and it is much narrower than one. An
        audit found this module treating it as though it were, with `supported`
        asking only whether a claim lay more than 1/n away, which at 21 flagged
        shipments calls a five point gap resolved when the sampling error alone
        is about six points. ADR-005 listed the arithmetic among the claims the
        fixture fully establishes, which it does not: it establishes the
        granularity bound. `sampling_half_width` is the other half.
        """
        if self.denominator == 0:
            raise AttributionError("a resolution floor over zero observations is undefined")
        return 1.0 / self.denominator

    @property
    def sampling_half_width(self) -> float:
        """Half a Wilson score interval around the measured rate, at the
        conventional ninety five per cent.

        Wilson rather than the normal approximation, because the rates this
        repository reports sit near one and the normal interval is worst exactly
        there: at 21 of 21 it returns a width of zero and declares a perfect
        sample. Wilson keeps a finite interval at the boundary, which is the
        whole reason to prefer it here.
        """
        if self.denominator == 0:
            raise AttributionError("a sampling interval over zero observations is undefined")
        z = 1.959963984540054  # the 97.5th percentile of the standard normal
        n = self.denominator
        rate = self.rate
        denominator = 1 + z**2 / n
        spread = z * math.sqrt(rate * (1 - rate) / n + z**2 / (4 * n**2)) / denominator
        return spread

    @property
    def resolution(self) -> float:
        """What this sample can actually resolve: the wider of the two bounds.

        The granularity floor is necessary and the sampling interval is what
        makes it sufficient, so a difference has to clear both and the larger
        one is the binding constraint. On every sample this repository reports
        it is the sampling interval.
        """
        return max(self.floor, self.sampling_half_width)

    @property
    def supported(self) -> bool:
        """Whether the sample can tell the measured rate from the claimed one.

        A rate measured at the top of its range and claimed five points below
        it is supported only if the sample is large enough that a shortfall that
        size would have shown up, which means clearing the sampling interval and
        not merely the granularity floor.
        """
        return abs(self.rate - self.claim) > self.resolution

    def samples_needed(self) -> int:
        """How many observations the claim would need to be distinguishable.

        Reported even when the claim is already supported, because a reader
        comparing two lanes needs to know which of them is resolving anything.

        Solved by search rather than by inverting a formula. The binding
        constraint is the Wilson half-width, which depends on the rate as well
        as the sample size and does not invert in closed form, and the previous
        answer of `1 / gap` inverted the granularity floor instead: at a five
        point gap it said twenty one observations where the sampling interval
        needs several hundred. Searching keeps the answer consistent with
        `supported`, which is the property it is supposed to predict, and a test
        asserts the two agree.
        """
        gap = abs(self.rate - self.claim)
        if gap <= 0:
            raise AttributionError(
                "a rate exactly equal to the claim needs an infinite sample to separate "
                "them; there is nothing to resolve"
            )
        # From one, not from the sample in hand. The question is how many
        # observations the claim needs, which is a property of the claim and the
        # rate; starting at the current denominator answers "how many more" and
        # returns the current size whenever it is already enough, which makes
        # the answer unfalsifiable.
        size = 1
        while size < self.MAX_SAMPLE:
            # The same measured rate, asked of a larger sample.
            scaled = RateWithFloor(round(self.rate * size), size, self.claim)
            if abs(scaled.rate - self.claim) > scaled.resolution:
                return size
            size += 1
        raise AttributionError(
            f"no sample below {self.MAX_SAMPLE} separates a rate of {self.rate:.4f} from a "
            f"claim of {self.claim:.4f}; the gap is too small to resolve at this scale"
        )


def rate_with_floor(numerator: int, denominator: int, claim: float) -> RateWithFloor:
    if denominator < 0 or numerator < 0:
        raise AttributionError("a rate cannot be built from negative counts")
    if numerator > denominator:
        raise AttributionError(
            f"numerator {numerator} exceeds denominator {denominator}; this is not a rate"
        )
    return RateWithFloor(numerator, denominator, claim)
