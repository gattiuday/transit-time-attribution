"""The attribution arithmetic, the conventions, and what it refuses."""

from __future__ import annotations

import dataclasses

import pytest

from tta.attribute import INFEASIBLE_PLAN, NOT_LATE, attribute, attribute_log, stage_lateness
from tta.config import SECONDS_PER_DAY, next_departure
from tta.errors import AttributionError


def test_an_on_plan_shipment_has_no_stage_over_plan(on_plan, one_lane, handling):
    lateness = stage_lateness(on_plan, one_lane, handling)
    assert all(value <= 0 for value in lateness.values())


def test_a_shipment_that_misses_its_cutoff_is_charged_a_whole_day(
    on_plan, one_lane, handling
):
    """The counterfactual, as an assertion: the charge is the departure the late
    release caused the shipment to miss, not the wait it then sat through."""
    late_release = dataclasses.replace(
        on_plan,
        released=one_lane.cutoff_hour * 3600 - handling + 60,
        ship_confirm=SECONDS_PER_DAY + one_lane.cutoff_hour * 3600,
    )
    lateness = stage_lateness(late_release, one_lane, handling)
    assert lateness["release_to_depart"] == SECONDS_PER_DAY


def test_an_early_release_is_never_charged_for_waiting(on_plan, one_lane, handling):
    """An early release can still sit in an unlucky part of the day. Charging
    that wait would blame the warehouse for the timetable, which an earlier
    version of this module did, and `experiments/exp01` caught it."""
    early = dataclasses.replace(on_plan, released=on_plan.planned_release - 4 * 3600)
    assert stage_lateness(early, one_lane, handling)["release_to_depart"] <= 0


def test_a_shipment_delivered_on_time_has_no_cause(on_plan, one_lane, handling):
    result = attribute(on_plan, one_lane, handling)
    assert result.cause == NOT_LATE
    assert not result.is_late
    assert result.shares == {}


def test_a_late_shipment_with_no_stage_over_plan_is_a_planning_failure(
    on_plan, one_lane, handling
):
    impossible = dataclasses.replace(
        on_plan, promised_delivery=on_plan.ship_confirm + on_plan.committed_transit - 7200
    )
    result = attribute(impossible, one_lane, handling)
    assert result.is_late
    assert result.cause == INFEASIBLE_PLAN


def test_the_largest_cause_convention_names_the_biggest_overrun(
    on_plan, one_lane, handling
):
    slow_transit = dataclasses.replace(
        on_plan,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
        released=on_plan.planned_release + 3600,
    )
    assert attribute(slow_transit, one_lane, handling, "largest_cause").cause == "transit"


def test_the_first_cause_convention_names_the_earliest_overrun(
    on_plan, one_lane, handling
):
    both = dataclasses.replace(
        on_plan,
        released=on_plan.planned_release + 3600,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
    )
    assert attribute(both, one_lane, handling, "first_cause").cause == "order_to_release"


def test_the_proportional_convention_splits_across_every_late_stage(
    on_plan, one_lane, handling
):
    both = dataclasses.replace(
        on_plan,
        released=on_plan.planned_release + 3600,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
    )
    result = attribute(both, one_lane, handling, "proportional")
    assert len(result.shares) > 1
    assert sum(result.shares.values()) == pytest.approx(1.0)


def test_an_unknown_convention_is_refused_by_name(on_plan, one_lane, handling):
    with pytest.raises(AttributionError, match="unknown convention 'blame_carrier'"):
        attribute(on_plan, one_lane, handling, "blame_carrier")


def test_an_upstream_cause_is_flagged_as_outside_the_scorecard(
    on_plan, one_lane, handling
):
    late_release = dataclasses.replace(
        on_plan,
        released=one_lane.cutoff_hour * 3600 - handling + 60,
        ship_confirm=SECONDS_PER_DAY + one_lane.cutoff_hour * 3600,
        delivered=SECONDS_PER_DAY + on_plan.delivered,
    )
    result = attribute(late_release, one_lane, handling)
    assert result.is_late
    assert result.upstream_of_carrier


def test_a_transit_cause_is_not_flagged_as_upstream(on_plan, one_lane, handling):
    slow = dataclasses.replace(on_plan, delivered=on_plan.delivered + 3 * SECONDS_PER_DAY)
    assert not attribute(slow, one_lane, handling).upstream_of_carrier


def test_an_on_time_shipment_is_not_flagged_as_upstream(on_plan, one_lane, handling):
    assert not attribute(on_plan, one_lane, handling).upstream_of_carrier


def test_the_attribution_round_trips_through_a_plain_dictionary(
    on_plan, one_lane, handling
):
    result = attribute(on_plan, one_lane, handling)
    assert type(result)(**result.as_dict()) == result


def test_an_empty_log_is_refused(lanes, handling):
    with pytest.raises(AttributionError, match="empty event log"):
        attribute_log([], lanes, handling)


def test_a_log_with_an_undeclared_lane_is_refused(on_plan, handling):
    with pytest.raises(AttributionError, match="no lane definition for"):
        attribute_log([on_plan], {}, handling)


def test_the_summary_counts_every_shipment(log, lanes, handling):
    summary, rows = attribute_log(log, lanes, handling)
    assert summary.shipments == len(log) == len(rows)


def test_the_on_time_rate_is_the_complement_of_the_late_count(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    assert summary.on_time_rate == pytest.approx(1 - summary.late / summary.shipments)


def test_the_cause_counts_sum_to_the_late_count(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    assert sum(summary.causes.values()) == summary.late


def test_most_late_deliveries_are_invisible_to_a_carrier_scorecard(log, lanes, handling):
    """The headline, as an assertion."""
    summary, _ = attribute_log(log, lanes, handling)
    assert summary.upstream_share_of_late > 0.5
    assert summary.late_but_carrier_looks_fine > summary.carrier_flagged


def test_the_upstream_share_is_undefined_when_nothing_was_late(
    on_plan, lanes, handling
):
    """Not zero. A rate with no denominator is undefined, and reporting zero
    would read as a perfect operation rather than as an empty question."""
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than zero"):
        _ = summary.upstream_share_of_late


def test_the_multiple_cause_share_is_undefined_when_nothing_was_late(
    on_plan, lanes, handling
):
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than zero"):
        _ = summary.multiple_cause_share


def test_scorecard_precision_is_undefined_when_nothing_was_flagged(
    on_plan, lanes, handling
):
    """Not perfect. A precision over zero flags is the absence of a measurement."""
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than perfect"):
        _ = summary.scorecard_precision


def test_the_scorecard_is_precise_on_the_fixture(log, lanes, handling):
    """It is rarely wrong about the shipments it flags. That is what makes it
    dangerous: a precise metric that sees a quarter of the problem reads as
    trustworthy."""
    summary, _ = attribute_log(log, lanes, handling)
    assert summary.scorecard_precision > 0.8


def test_the_summary_round_trips_through_a_plain_dictionary(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    assert type(summary)(**summary.as_dict()) == summary


def test_the_counterfactual_departure_is_the_one_an_on_plan_release_would_catch(
    on_plan, one_lane, handling
):
    assert next_departure(on_plan.planned_release + handling, one_lane) == on_plan.ship_confirm
