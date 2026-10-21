"""The attribution arithmetic, the conventions, and what it refuses."""

from __future__ import annotations

import dataclasses

import pytest

from tta.attribute import (
    INFEASIBLE_PLAN,
    NOT_LATE,
    attribute,
    attribute_log,
    promise_slack,
    residual,
    stage_lateness,
    stage_overruns,
)
from tta.config import SECONDS_PER_DAY, next_departure
from tta.errors import AttributionError
from tta.stages import Shipment


def test_an_on_plan_shipment_has_no_stage_over_plan(on_plan, one_lane, handling):
    lateness = stage_lateness(on_plan, one_lane, handling)
    assert all(value <= 0 for value in lateness.values())


def test_a_missed_cutoff_costs_a_whole_day_split_across_the_two_upstream_stages(
    on_plan, one_lane, handling
):
    """The counterfactual, as an assertion, and the double charge as a guard.

    This test used to assert that the departure alone was charged the whole day.
    It passed, and it was the double charge written down: the release overrun
    that caused the miss was charged the overrun on top of it, so the two
    upstream stages together billed a day plus the overrun for a day of delay.
    What the day is split between is a convention. That the two sum to exactly
    one day is not.
    """
    released = one_lane.cutoff_hour * 3600 - handling + 60
    late_release = dataclasses.replace(
        on_plan,
        released=released,
        ship_confirm=SECONDS_PER_DAY + one_lane.cutoff_hour * 3600,
    )
    lateness = stage_lateness(late_release, one_lane, handling)
    overrun = released - on_plan.planned_release
    assert lateness["order_to_release"] == overrun
    assert lateness["release_to_depart"] == SECONDS_PER_DAY - overrun
    assert lateness["order_to_release"] + lateness["release_to_depart"] == SECONDS_PER_DAY


def test_an_early_release_is_never_blamed_for_waiting(on_plan, one_lane, handling):
    """An early release can still sit in an unlucky part of the day.

    Blaming that wait would charge the warehouse for the timetable, which an
    earlier version of this module did and `experiments/exp01` caught. The
    reconciling charge still shows the credit being spent in the wait, because
    the charges must sum to the lateness; `stage_overruns` is the decomposition
    that decides blame, and it must show nothing over plan at all.
    """
    early = dataclasses.replace(on_plan, released=on_plan.planned_release - 4 * 3600)
    overruns = stage_overruns(early, one_lane, handling)
    assert overruns["order_to_release"] == 0
    assert overruns["release_to_depart"] == 0
    charges = stage_lateness(early, one_lane, handling)
    assert charges["order_to_release"] + charges["release_to_depart"] == 0


def test_a_shipment_delivered_on_time_has_no_cause(on_plan, one_lane, handling):
    result = attribute(on_plan, one_lane, handling)
    assert result.cause == NOT_LATE
    assert not result.is_late
    assert result.shares == {}


def test_a_late_shipment_with_no_stage_over_plan_is_a_planning_failure(on_plan, one_lane, handling):
    impossible = dataclasses.replace(
        on_plan, promised_delivery=on_plan.ship_confirm + on_plan.committed_transit - 7200
    )
    result = attribute(impossible, one_lane, handling)
    assert result.is_late
    assert result.cause == INFEASIBLE_PLAN


def test_the_largest_cause_convention_names_the_biggest_overrun(on_plan, one_lane, handling):
    slow_transit = dataclasses.replace(
        on_plan,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
        released=on_plan.planned_release + 3600,
    )
    assert attribute(slow_transit, one_lane, handling, "largest_cause").cause == "transit"


def test_the_first_cause_convention_names_the_earliest_overrun(on_plan, one_lane, handling):
    both = dataclasses.replace(
        on_plan,
        released=on_plan.planned_release + 3600,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
    )
    assert attribute(both, one_lane, handling, "first_cause").cause == "order_to_release"


def test_the_proportional_convention_splits_across_every_late_stage(on_plan, one_lane, handling):
    both = dataclasses.replace(
        on_plan,
        released=on_plan.planned_release + 3600,
        delivered=on_plan.delivered + 3 * SECONDS_PER_DAY,
    )
    result = attribute(both, one_lane, handling, "proportional")
    assert len(result.shares) > 1
    # Summing to one is true by construction of the normalisation, so on its own
    # this asserts nothing. What it is worth checking is that the shares are
    # shares of the lateness being explained rather than of some larger total:
    # under the double charge the denominator was nearly twice the delivery's
    # lateness, so every share was a fraction of a quantity that did not exist.
    assert sum(result.shares.values()) == pytest.approx(1.0)
    assert residual(both, one_lane, handling) == 0
    overruns = stage_overruns(both, one_lane, handling)
    for stage, share in result.shares.items():
        assert share == pytest.approx(overruns[stage] / sum(overruns.values()))


def test_an_unknown_convention_is_refused_by_name(on_plan, one_lane, handling):
    with pytest.raises(AttributionError, match="unknown convention 'blame_carrier'"):
        attribute(on_plan, one_lane, handling, "blame_carrier")


def test_an_upstream_cause_is_flagged_as_outside_the_scorecard(on_plan, one_lane, handling):
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


def test_the_attribution_round_trips_through_a_plain_dictionary(on_plan, one_lane, handling):
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


def test_the_upstream_share_is_undefined_when_nothing_was_late(on_plan, lanes, handling):
    """Not zero. A rate with no denominator is undefined, and reporting zero
    would read as a perfect operation rather than as an empty question."""
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than zero"):
        _ = summary.upstream_share_of_late


def test_the_multiple_cause_share_is_undefined_when_nothing_was_late(on_plan, lanes, handling):
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than zero"):
        _ = summary.multiple_cause_share


def test_scorecard_precision_is_undefined_when_nothing_was_flagged(on_plan, lanes, handling):
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


# --------------------------------------------------------------------------
# The reconciliation identity.
#
# The first version of this package charged the release overrun twice: once as
# itself and once as the departure it pushed. Nothing reconciled the charges
# against the lateness they were explaining, so the error survived a full test
# suite, a green CI run and a receipts system, and was found by an audit that
# simply added the three numbers up. These tests are that addition, run over
# every shipment rather than over an example.
# --------------------------------------------------------------------------


def test_the_charges_reconcile_against_the_lateness_for_every_shipment(log, lanes, handling):
    """The identity the whole decomposition rests on.

        delivery_lateness = order_to_release + release_to_depart + transit - slack

    If this fails, every figure this repository publishes is a figure about
    something other than the lateness it claims to decompose.
    """
    offenders = [
        (shipment.shipment_id, residual(shipment, lanes[shipment.lane], handling))
        for shipment in log
        if residual(shipment, lanes[shipment.lane], handling) != 0
    ]
    assert not offenders, (
        f"the charges do not add up on {len(offenders)} shipments: {offenders[:5]}"
    )


def test_the_charges_do_not_sum_past_the_lateness_they_explain(log, lanes, handling):
    """The double charge, stated as the symptom an audit would look for.

    Under the version that charged the overrun twice this failed on 88.4% of
    late deliveries and the charges totalled 1.93 times the lateness. Positive
    charges may still exceed the lateness when another charge is negative, so
    this compares the signed sum, which is what the identity constrains.
    """
    for shipment in log:
        lane = lanes[shipment.lane]
        charges = stage_lateness(shipment, lane, handling)
        slack = promise_slack(shipment, lane, handling)
        assert sum(charges.values()) - slack == shipment.delivery_lateness


def test_a_release_that_misses_nothing_is_charged_nothing_for_the_departure(one_lane, handling):
    """The property the counterfactual exists for, which netting must not break."""
    planned = 8 * 3600
    departure = next_departure(planned + handling, one_lane)
    shipment = Shipment(
        shipment_id="SHP-ONPLAN",
        lane=one_lane.name,
        order_created=0,
        released=planned,
        ship_confirm=departure,
        delivered=departure + 2 * 86_400,
        promised_delivery=departure + 2 * 86_400,
        planned_release=planned,
        committed_transit=2 * 86_400,
    )
    charges = stage_lateness(shipment, one_lane, handling)
    assert charges["order_to_release"] == 0
    assert charges["release_to_depart"] == 0


def test_the_departure_is_charged_only_the_wait_the_overrun_did_not_force(one_lane, handling):
    """A single departure lane, where the whole amplification is the timetable.

    A release nine hours late on a lane with one departure a day pushes the
    departure by a full day. Nine of those hours are the overrun and are charged
    to the warehouse; the remaining fifteen are what the timetable added, and
    charging all twenty four to the departure as well would bill the nine twice.
    """
    planned = 6 * 3600
    overrun = 9 * 3600
    released = planned + overrun
    shipment = Shipment(
        shipment_id="SHP-OVERRAN",
        lane=one_lane.name,
        order_created=0,
        released=released,
        ship_confirm=next_departure(released + handling, one_lane),
        delivered=next_departure(released + handling, one_lane) + 2 * 86_400,
        promised_delivery=next_departure(planned + handling, one_lane) + 2 * 86_400,
        planned_release=planned,
        committed_transit=2 * 86_400,
    )
    charges = stage_lateness(shipment, one_lane, handling)
    displacement = shipment.ship_confirm - next_departure(planned + handling, one_lane)
    assert charges["order_to_release"] == overrun
    assert charges["release_to_depart"] == displacement - overrun
    assert charges["order_to_release"] + charges["release_to_depart"] == displacement


def test_infeasible_plan_is_exactly_negative_slack(log, lanes, handling, truth):
    """The derivation, checked in both directions.

    `infeasible_plan` used to be inferred from a late delivery with no stage
    over its plan, which made it the branch that caught anything the arithmetic
    could not explain. It is now negative slack, and these two sets must be the
    same set.
    """
    derived = {
        shipment.shipment_id
        for shipment in log
        if promise_slack(shipment, lanes[shipment.lane], handling) < 0
    }
    planted = {
        shipment.shipment_id
        for shipment, cause in zip(log, truth, strict=True)
        if cause == "infeasible_plan"
    }
    assert derived == planted


@pytest.mark.parametrize("measure", ["stage_share_of_late", "infeasible_share_of_late"])
def test_the_split_of_the_upstream_share_is_undefined_when_nothing_was_late(
    on_plan, lanes, handling, measure
):
    """The same rule as the share they split, for the same reason."""
    summary, _ = attribute_log([on_plan], lanes, handling)
    with pytest.raises(AttributionError, match="undefined rather than zero"):
        _ = getattr(summary, measure)


def test_the_upstream_share_is_the_stage_share_plus_the_infeasible_share(log, lanes, handling):
    """The headline counts a cause that is not a stage, so it has to split.

    `infeasible_plan` belongs in what a scorecard cannot see and does not belong
    in a sentence that says "a stage". Publishing the two parts is what lets the
    headline say which it means.
    """
    summary, _ = attribute_log(log, lanes, handling)
    assert summary.stage_share_of_late + summary.infeasible_share_of_late == pytest.approx(
        summary.upstream_share_of_late
    )
