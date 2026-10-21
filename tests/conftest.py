"""Shared fixtures. Everything deterministic; no test may touch the network."""

from __future__ import annotations

import pytest

from tta.config import LANES
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.stages import SECONDS_PER_DAY, Shipment

#: Maps each planted cause to the stage the attribution should name, where the
#: shipment actually arrived late. Used by the grading tests and by exp01.
EXPECTED_CAUSE = {
    "warehouse": "order_to_release",
    "missed_cutoff": "release_to_depart",
    "carrier": "transit",
    "infeasible_plan": "infeasible_plan",
    "none": "not_late",
}


@pytest.fixture(scope="session")
def log_and_truth():
    return generate_log(2_000)


@pytest.fixture(scope="session")
def log(log_and_truth):
    return log_and_truth[0]


@pytest.fixture(scope="session")
def truth(log_and_truth):
    return log_and_truth[1]


@pytest.fixture(scope="session")
def lanes():
    return lanes_by_name()


@pytest.fixture
def handling():
    return DEPART_FLOOR_SECONDS


@pytest.fixture
def one_lane():
    return LANES[0]


@pytest.fixture
def on_plan(one_lane):
    """A shipment that releases on plan, makes its departure and arrives early."""
    planned_release = 6 * 3600
    depart = one_lane.cutoff_hour * 3600
    transit = one_lane.committed_transit_days * SECONDS_PER_DAY
    return Shipment(
        shipment_id="ON-PLAN",
        lane=one_lane.name,
        order_created=0,
        released=planned_release,
        ship_confirm=depart,
        delivered=depart + transit,
        promised_delivery=depart + transit + 3600,
        planned_release=planned_release,
        committed_transit=transit,
    )
