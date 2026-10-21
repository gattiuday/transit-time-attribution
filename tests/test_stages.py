"""The lifecycle model, and the timestamps it refuses."""

from __future__ import annotations

import dataclasses

import pytest

from tta.config import LANES, departure_slots, next_departure
from tta.errors import UnattributableShipment
from tta.stages import CARRIER_STAGE, SECONDS_PER_DAY, STAGES, Shipment


def test_the_three_stages_are_named_in_lifecycle_order():
    assert STAGES == ("order_to_release", "release_to_depart", "transit")


def test_only_transit_lies_inside_a_carrier_scorecard():
    assert CARRIER_STAGE == "transit"
    assert CARRIER_STAGE in STAGES


def test_stage_durations_partition_the_lifecycle(on_plan):
    durations = on_plan.stage_durations
    assert sum(durations.values()) == on_plan.delivered - on_plan.order_created


def test_an_on_plan_shipment_is_not_late(on_plan):
    assert on_plan.delivery_lateness < 0
    assert not on_plan.is_late(60)


def test_an_on_plan_shipment_does_not_look_late_to_a_scorecard(on_plan):
    assert not on_plan.carrier_looks_late(60)


def test_delivery_lateness_is_measured_against_the_promise_not_the_plan(on_plan):
    later = dataclasses.replace(on_plan, delivered=on_plan.promised_delivery + 7200)
    assert later.delivery_lateness == 7200
    assert later.is_late(60)


def test_carrier_lateness_is_measured_against_the_committed_window(on_plan):
    slow = dataclasses.replace(on_plan, delivered=on_plan.delivered + 3600)
    assert slow.carrier_transit_lateness == 3600


def test_a_carrier_can_beat_its_window_on_a_shipment_delivered_late(on_plan):
    """The case a scorecard reports as a carrier success and a customer reports
    as a failure. Both are correct about different things."""
    late = dataclasses.replace(
        on_plan,
        delivered=on_plan.delivered - 1800,
        promised_delivery=on_plan.delivered - 7200,
    )
    assert late.is_late(60)
    assert late.carrier_transit_lateness < 0


def test_release_lateness_is_measured_against_the_planned_release(on_plan):
    slow = dataclasses.replace(on_plan, released=on_plan.planned_release + 5400)
    assert slow.release_lateness == 5400


def test_a_shipment_delivered_before_it_shipped_is_refused(on_plan):
    broken = dataclasses.replace(on_plan, delivered=on_plan.ship_confirm - 1)
    with pytest.raises(UnattributableShipment, match="delivered before ship_confirm"):
        broken.validate()


def test_a_shipment_shipped_before_it_was_released_is_refused(on_plan):
    broken = dataclasses.replace(on_plan, ship_confirm=on_plan.released - 1)
    with pytest.raises(UnattributableShipment, match="ship_confirm before released"):
        broken.validate()


def test_a_shipment_released_before_it_was_ordered_is_refused(on_plan):
    broken = dataclasses.replace(on_plan, order_created=on_plan.released + 1)
    with pytest.raises(UnattributableShipment, match="released before order_created"):
        broken.validate()


def test_a_shipment_with_no_committed_transit_is_refused(on_plan):
    broken = dataclasses.replace(on_plan, committed_transit=0)
    with pytest.raises(UnattributableShipment, match="committed transit"):
        broken.validate()


def test_validate_returns_the_shipment_so_it_can_be_chained(on_plan):
    assert on_plan.validate() is on_plan


def test_a_shipment_round_trips_through_a_plain_dictionary(on_plan):
    assert type(on_plan)(**on_plan.as_dict()) == on_plan


def test_a_single_departure_lane_leaves_at_its_cutoff():
    lane = next(lane for lane in LANES if lane.departures_per_day == 1)
    assert departure_slots(lane) == [lane.cutoff_hour * 3600]


def test_a_multi_departure_lane_has_one_slot_per_departure():
    lane = next(lane for lane in LANES if lane.departures_per_day > 1)
    assert len(departure_slots(lane)) == lane.departures_per_day


def test_every_departure_slot_falls_on_or_before_the_cutoff():
    for lane in LANES:
        assert max(departure_slots(lane)) <= lane.cutoff_hour * 3600


def test_a_shipment_ready_before_the_cutoff_leaves_the_same_day(one_lane):
    ready = one_lane.cutoff_hour * 3600 - 60
    assert next_departure(ready, one_lane) == one_lane.cutoff_hour * 3600


def test_a_shipment_ready_after_the_cutoff_waits_for_tomorrow(one_lane):
    """Minutes of lateness become a day of lateness. The step that a scorecard
    starting at ship confirm cannot see."""
    ready = one_lane.cutoff_hour * 3600 + 60
    tomorrow = SECONDS_PER_DAY + one_lane.cutoff_hour * 3600
    assert next_departure(ready, one_lane) == tomorrow


def test_a_minute_late_costs_a_whole_day_on_a_single_departure_lane(one_lane):
    on_time = next_departure(one_lane.cutoff_hour * 3600, one_lane)
    just_late = next_departure(one_lane.cutoff_hour * 3600 + 60, one_lane)
    assert just_late - on_time == SECONDS_PER_DAY


def test_more_departures_reduce_the_cost_of_missing_one():
    """Why the fixture carries lanes with one departure and with three."""
    single = next(lane for lane in LANES if lane.departures_per_day == 1)
    multi = next(lane for lane in LANES if lane.departures_per_day > 1)
    slots = departure_slots(multi)
    cost_multi = slots[1] - slots[0]
    assert cost_multi < SECONDS_PER_DAY
    assert departure_slots(single) == [single.cutoff_hour * 3600]
