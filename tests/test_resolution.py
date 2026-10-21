"""Timestamp granularity, and the floor under every rate."""

from __future__ import annotations

import pytest

from tta.attribute import attribute_log
from tta.config import GRANULARITIES
from tta.errors import AttributionError
from tta.resolution import coarsen, rate_with_floor


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
        summary, _ = attribute_log(
            [coarsen(s, granularity) for s in log], lanes, handling
        )
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


def test_the_sample_needed_to_separate_a_claim_is_arithmetic():
    assert rate_with_floor(100, 100, 0.95).samples_needed() == 20


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
