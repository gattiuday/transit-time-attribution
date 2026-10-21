"""Timestamp granularity, and the floor under every rate."""

from __future__ import annotations

import pytest

from tta.attribute import attribute_log
from tta.config import GRANULARITIES
from tta.errors import AttributionError
from tta.resolution import coarsen, rate_with_floor, separates, wilson_interval


@pytest.mark.parametrize("granularity", sorted(GRANULARITIES))
def test_coarsening_leaves_every_timestamp_on_its_grid(on_plan, granularity):
    step = GRANULARITIES[granularity]
    coarse = coarsen(on_plan, granularity)
    for field in ("order_created", "released", "ship_confirm", "delivered"):
        assert getattr(coarse, field) % step == 0


def test_coarsening_preserves_the_committed_transit(on_plan):
    """The commitment is a contract term, not an observed timestamp, so rounding
    it would change what the carrier agreed to rather than how precisely it was
    recorded."""
    assert coarsen(on_plan, "day").committed_transit == on_plan.committed_transit


def test_flooring_never_moves_a_timestamp_later(on_plan):
    coarse = coarsen(on_plan, "hour", "floor")
    assert coarse.released <= on_plan.released


def test_rounding_to_nearest_can_move_a_timestamp_later(on_plan):
    """Which is why the mode is a parameter: flooring hides a near miss and
    rounding can invent one. ADR-002."""
    shifted = coarsen(on_plan, "day", "nearest")
    floored = coarsen(on_plan, "day", "floor")
    assert shifted.released >= floored.released


def test_an_unknown_granularity_is_refused_by_name(on_plan):
    with pytest.raises(AttributionError, match="unknown granularity 'fortnight'"):
        coarsen(on_plan, "fortnight")


def test_an_unknown_rounding_mode_is_refused_by_name(on_plan):
    with pytest.raises(AttributionError, match="unknown rounding mode"):
        coarsen(on_plan, "hour", "upwards")


def test_minute_granularity_barely_changes_the_attribution(log, lanes, handling):
    fine, _ = attribute_log(log, lanes, handling)
    coarse, _ = attribute_log([coarsen(s, "minute") for s in log], lanes, handling)
    assert abs(fine.late - coarse.late) <= max(2, fine.late // 100)


def test_day_granularity_loses_most_of_the_lateness(log, lanes, handling):
    """It does not fail loudly. It reports fewer late shipments and a different
    mix, which reads as a better operation."""
    fine, _ = attribute_log(log, lanes, handling)
    coarse, _ = attribute_log([coarsen(s, "day") for s in log], lanes, handling)
    assert coarse.late < fine.late * 0.75


def test_coarser_granularity_never_sharpens_the_attribution(log, lanes, handling):
    counts = []
    for granularity in ("minute", "quarter_hour", "hour", "day"):
        summary, _ = attribute_log([coarsen(s, granularity) for s in log], lanes, handling)
        counts.append(summary.late)
    assert counts[0] >= counts[-1]


def test_a_rate_reports_its_own_resolution_floor():
    rate = rate_with_floor(40, 40, 0.95)
    assert rate.rate == 1.0
    assert rate.floor == pytest.approx(1 / 40)


def test_a_perfect_rate_over_a_small_sample_cannot_support_a_high_claim():
    """100% over eleven flags is "above ten in eleven", and a 95% claim sits
    inside that. Reporting it as 100% is the most common way a portfolio
    overclaims."""
    assert not rate_with_floor(11, 11, 0.95).supported


def test_a_perfect_rate_over_a_large_sample_can_support_the_same_claim():
    assert rate_with_floor(400, 400, 0.95).supported


def test_a_measured_zero_is_reported_as_below_its_floor():
    rate = rate_with_floor(0, 34, 0.0)
    assert rate.rate == 0.0
    assert rate.floor == pytest.approx(1 / 34)


def test_the_sample_needed_to_separate_a_claim_agrees_with_supported():
    """The property `samples_needed` exists to predict, checked against it.

    This asserted a literal 20, which was `1 / gap` and inverted the granularity
    floor rather than the constraint that actually binds. A perfect rate claimed
    five points lower is not separable at twenty observations: the Wilson
    interval there is about twenty points wide. The answer and the predicate
    have to agree, so the test asks whether they do rather than restating one of
    them as a constant.
    """
    rate = rate_with_floor(100, 100, 0.95)
    needed = rate.samples_needed()
    assert not rate_with_floor(needed - 1, needed - 1, 0.95).supported
    assert rate_with_floor(needed, needed, 0.95).supported


def test_the_granularity_floor_is_never_the_binding_constraint_on_these_samples():
    """One over n is a statement about granularity, not about sampling error.

    Treating it as an interval is the defect an audit found: at 21 flagged
    shipments it calls a five point gap resolved while the sampling error alone
    is nearly eight points. The floor is kept, because a difference below 1/n
    genuinely cannot be expressed, and the wider of the two is what decides.
    """
    for numerator, denominator in ((21, 21), (19, 21), (93, 100), (232, 250), (1852, 2000)):
        rate = rate_with_floor(numerator, denominator, 0.95)
        assert rate.sampling_half_width > rate.floor
        assert rate.resolution == rate.sampling_half_width


def test_a_perfect_rate_still_has_an_interval():
    """Why Wilson and not the normal approximation.

    At 21 of 21 the normal interval is sqrt(p(1-p)/n) = 0, which would declare a
    sample of twenty one flags able to resolve anything at all.
    """
    rate = rate_with_floor(21, 21, 0.95)
    assert rate.rate == 1.0
    assert rate.sampling_half_width > 0.07
    assert not rate.supported


def test_an_unresolvable_gap_is_refused_rather_than_searched_forever():
    rate = rate_with_floor(950_001, 1_000_000, 0.95)
    with pytest.raises(AttributionError, match="too small to resolve"):
        rate.samples_needed()


def test_a_claim_exactly_equal_to_the_measurement_cannot_be_separated():
    with pytest.raises(AttributionError, match="nothing to resolve"):
        rate_with_floor(95, 100, 0.95).samples_needed()


def test_a_rate_over_zero_observations_is_undefined_not_zero():
    with pytest.raises(AttributionError, match="undefined, not zero"):
        _ = rate_with_floor(0, 0, 0.95).rate


def test_a_floor_over_zero_observations_is_undefined():
    with pytest.raises(AttributionError, match="floor over zero observations"):
        _ = rate_with_floor(0, 0, 0.95).floor


def test_a_numerator_above_its_denominator_is_refused():
    with pytest.raises(AttributionError, match="is not a rate"):
        rate_with_floor(12, 10, 0.95)


def test_negative_counts_are_refused():
    with pytest.raises(AttributionError, match="negative counts"):
        rate_with_floor(-1, 10, 0.95)


def test_the_wilson_interval_is_not_centred_on_the_measured_rate():
    """The defect that made `supported` test a different interval.

    Wilson is symmetric about (p + z^2/2n)/(1 + z^2/n). At zero successes over
    forty trials the interval reaches 8.76% while the rate plus a half width
    reaches 4.38%, so a claim of 6% was reported as separable when it is inside
    the interval the sample supports.
    """
    rate = rate_with_floor(0, 40, 0.06)
    lower, upper = rate.interval
    assert lower == pytest.approx(0.0, abs=1e-9)
    assert upper == pytest.approx(0.0876, abs=5e-4)
    assert not rate.supported
    assert rate_with_floor(0, 40, 0.10).supported


def test_the_interval_and_the_half_width_disagree_about_the_bound():
    """Kept explicit, because the two were used interchangeably."""
    rate = rate_with_floor(0, 40, 0.0)
    _, upper = rate.interval
    assert upper > rate.rate + rate.sampling_half_width


def test_the_sample_needed_is_a_threshold_and_not_the_first_lucky_size():
    """Monotonicity, over the repository's own measured precision.

    `samples_needed` rounded the numerator back to an integer at each candidate
    size, which moved the effective rate by up to half an observation. An audit
    found seventeen sizes above the returned answer that did not separate the
    claim, at the precision this repository publishes.
    """
    rate = rate_with_floor(292, 316, 0.95)
    needed = rate.samples_needed()
    assert not separates(rate.rate, needed - 1, 0.95)
    for size in range(needed, needed + 500):
        assert separates(rate.rate, size, 0.95), f"a sample of {size} stopped separating"


def test_an_interval_over_no_observations_is_undefined():
    with pytest.raises(AttributionError, match="undefined"):
        wilson_interval(0.5, 0)
