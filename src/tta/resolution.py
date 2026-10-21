"""What timestamp granularity costs an attribution, and the floor under every rate.

Two separate limits, both easy to leave out of a report and both capable of
reversing a conclusion.

The first is granularity. A transport system that records milestones to the
hour cannot see a release that missed a 16:00 cutoff by six minutes: rounded to
the hour it either made the cutoff or missed it by an hour, and which of those
appears depends on the rounding rule rather than on what happened. Every
attribution that depends on a near miss is lost at that granularity, and the
share lost is measurable rather than arguable.

The second is what a measured rate can support, which takes two bounds and not
one. A rate over n observations can only take the values k/n, so a difference
below one over n cannot be expressed: that is the granularity floor. It is not a
confidence interval and it is much narrower than one, and this module used it as
though it were the whole answer until an audit pointed out that a perfect
precision over a handful of flags has a sampling interval several times wider
than its floor. Both are computed here, the wider one decides, and the sample a
claim needs is solved against it rather than by inverting the floor.
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


#: The 97.5th percentile of the standard normal, for a two sided interval at the
#: conventional ninety five per cent.
Z_975 = 1.959963984540054


def wilson_interval(rate: float, size: int) -> tuple[float, float]:
    """The Wilson score interval for a rate observed over `size` trials.

    Takes the rate as a float rather than a count so that it can be asked of a
    hypothetical sample size without rounding the numerator back to an integer.
    `samples_needed` used to do exactly that, and `round(rate * size)` moved the
    effective rate by up to half an observation, which made the search
    non-monotone: an audit found sizes above the returned answer that did not
    separate the claim, so the answer was the first lucky size rather than a
    threshold. At a fixed rate the width shrinks monotonically in the size, so
    searching without the rounding returns a threshold.
    `test_the_sample_needed_is_a_threshold_and_not_the_first_lucky_size` walks
    five hundred sizes above the answer and is the check that this holds.
    """
    if size <= 0:
        raise AttributionError("a sampling interval over zero observations is undefined")
    z = Z_975
    denominator = 1 + z**2 / size
    centre = (rate + z**2 / (2 * size)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / size + z**2 / (4 * size**2)) / denominator
    return (centre - spread, centre + spread)


def separates(rate: float, size: int, claim: float) -> bool:
    """Whether a sample of `size` at `rate` puts `claim` outside what it supports."""
    lower, upper = wilson_interval(rate, size)
    return not (lower <= claim <= upper) and abs(rate - claim) > 1.0 / size


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
        asking only whether a claim lay more than one over n away, which on the
        smallest sample this repository reports calls a five point gap resolved
        while the interval around the same rate is more than twice that wide.
        ADR-005 listed the arithmetic among the claims the fixture fully
        establishes, which was true only of the granularity bound; that entry
        now says so and names both. `sampling_half_width` is the other half.
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
        there: at a perfect rate it returns a width of zero and declares a perfect
        sample. Wilson keeps a finite interval at the boundary, which is the
        whole reason to prefer it here.
        """
        lower, upper = wilson_interval(self.rate, self.denominator)
        return (upper - lower) / 2

    @property
    def interval(self) -> tuple[float, float]:
        """The Wilson score interval itself, which is not centred on the rate.

        Wilson is symmetric about (p + z^2/2n) / (1 + z^2/n), not about p, and
        the difference is largest exactly where this repository reports rates:
        near one, and at zero. `supported` compared the claim against p plus or
        minus the half width, which is a different interval from this one, and an
        audit found hundreds of combinations of sample size, successes and claim
        where that comparison called a claim distinguishable while the claim sat
        inside the real interval. At no misattributions over forty flags it put
        the bound at half of where the interval actually reaches. `tests/
        test_resolution.py` pins that case with both numbers, where a test can
        fail if either moves.
        """
        return wilson_interval(self.rate, self.denominator)

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

        The claim is supported when it lies outside the interval the sample
        actually supports, and that interval is `interval`, not the rate plus or
        minus a half width. It must also clear the granularity floor, because a
        difference a rate cannot express is not a difference this sample saw.
        """
        return separates(self.rate, self.denominator, self.claim)

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
            # The same measured rate, asked of a larger sample, without rounding
            # the numerator back to an integer. See `wilson_interval`.
            if separates(self.rate, size, self.claim):
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
