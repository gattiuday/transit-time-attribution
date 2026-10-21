"""Does the attribution recover a cause that was planted? Written before any claim.

The lesson this file exists to apply: a sibling repository shipped a simulator
that nothing graded, and when its own stated grading criterion was finally
pointed at it, it was wrong and had been from the start. So this file was
written before the README, and the generator plants the answer so there is
something to grade against.
"""

from __future__ import annotations

from collections import Counter

import pytest
from conftest import EXPECTED_CAUSE

from tta.attribute import attribute_log
from tta.errors import AttributionError
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name


def _graded(convention: str, shipments: int = 2_000):
    log, truth = generate_log(shipments)
    _, rows = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
    return [(planted, row) for planted, row in zip(truth, rows, strict=True) if row.is_late]


def test_a_carrier_overrun_is_attributed_to_transit():
    graded = _graded("largest_cause")
    carrier = [row for planted, row in graded if planted == "carrier"]
    assert carrier
    assert all(row.cause == "transit" for row in carrier)


def test_a_missed_cutoff_is_attributed_to_the_departure_wait():
    """The case a carrier scorecard is blind to by construction."""
    graded = _graded("largest_cause")
    missed = [row for planted, row in graded if planted == "missed_cutoff"]
    assert missed
    assert all(row.cause == "release_to_depart" for row in missed)


def test_an_infeasible_plan_is_not_blamed_on_an_operation():
    """Late with no stage over plan is a planning failure, and naming a stage
    would blame an operation for arithmetic done before it started."""
    graded = _graded("largest_cause")
    infeasible = [row for planted, row in graded if planted == "infeasible_plan"]
    assert infeasible
    assert all(row.cause == "infeasible_plan" for row in infeasible)


def test_a_warehouse_overrun_is_attributed_to_the_warehouse_under_first_cause():
    graded = _graded("first_cause")
    warehouse = [row for planted, row in graded if planted == "warehouse"]
    assert warehouse
    assert all(row.cause == "order_to_release" for row in warehouse)


def test_no_shipment_planted_as_on_plan_is_reported_late():
    """If one were, the generator's label would be false and every recovery rate
    in this repository would be grading the generator rather than the tool."""
    graded = _graded("largest_cause")
    assert not [row for planted, row in graded if planted == "none"]


@pytest.mark.parametrize("convention", ["first_cause", "largest_cause", "proportional"])
def test_the_upstream_share_is_the_same_under_every_convention(convention):
    """The headline claim does not depend on the arbitrary step.

    Both upstream stages lie outside a carrier scorecard's window, so which of
    them a convention names cannot change how much of the lateness the scorecard
    cannot see. If this ever fails, the headline has become convention
    dependent and the README has to say so."""
    log, _ = generate_log(2_000)
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
    baseline, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, "largest_cause")
    assert summary.upstream_share_of_late == pytest.approx(baseline.upstream_share_of_late)


def test_no_convention_recovers_every_planted_cause():
    """The structural limit, pinned rather than papered over.

    A release that overran by six hours has also missed the day's last
    departure. Both stages are over plan and both statements are true, so
    `first_cause` recovers the warehouse and loses the missed cutoff while
    `largest_cause` does the reverse. Neither clears three quarters, and a
    version of this repository that claimed otherwise would be claiming the data
    answers a question it cannot."""
    for convention in ("first_cause", "largest_cause"):
        graded = _graded(convention)
        correct = sum(1 for planted, row in graded if EXPECTED_CAUSE[planted] == row.cause)
        assert 0.6 < correct / len(graded) < 0.8


def test_the_two_single_cause_conventions_fail_on_opposite_groups():
    """Which is why the tool reports the convention beside every number."""
    first = Counter(
        planted for planted, row in _graded("first_cause") if EXPECTED_CAUSE[planted] != row.cause
    )
    largest = Counter(
        planted for planted, row in _graded("largest_cause") if EXPECTED_CAUSE[planted] != row.cause
    )
    assert first.most_common(1)[0][0] == "missed_cutoff"
    assert largest.most_common(1)[0][0] == "warehouse"


def test_most_late_shipments_have_more_than_one_stage_over_plan():
    """The reason no convention can win. Published, not hidden."""
    log, _ = generate_log(2_000)
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
    assert summary.multiple_cause_share > 0.5


def test_recovery_holds_on_a_larger_log():
    """A recovery rate measured once on one log is one draw."""
    rates = []
    for shipments in (2_000, 4_000):
        graded = _graded("largest_cause", shipments)
        rates.append(
            sum(1 for planted, row in graded if EXPECTED_CAUSE[planted] == row.cause) / len(graded)
        )
    assert abs(rates[0] - rates[1]) < 0.05


def test_a_cause_mix_that_does_not_sum_to_one_is_refused():
    with pytest.raises(AttributionError, match="must sum to 1"):
        generate_log(100, cause_mix={"none": 0.5, "carrier": 0.2})


def test_an_unknown_cause_in_the_mix_is_refused_by_name():
    with pytest.raises(AttributionError, match="unknown cause"):
        generate_log(100, cause_mix={"none": 0.5, "weather": 0.5})


def test_a_log_of_zero_shipments_is_refused():
    with pytest.raises(AttributionError, match="at least 1"):
        generate_log(0)


def test_the_generator_is_reproducible_for_a_fixed_seed():
    first, first_truth = generate_log(200, seed=11)
    second, second_truth = generate_log(200, seed=11)
    assert [s.as_dict() for s in first] == [s.as_dict() for s in second]
    assert first_truth == second_truth


def test_a_different_seed_produces_a_different_log():
    first, _ = generate_log(200, seed=11)
    second, _ = generate_log(200, seed=12)
    assert [s.as_dict() for s in first] != [s.as_dict() for s in second]


def test_a_carrier_only_log_leaves_the_scorecard_measuring_what_matters():
    """The control case. Where the lateness really is the carrier's, the
    scorecard sees it, and a tool that reported otherwise on every input would
    be measuring its own assumptions."""
    log, _ = generate_log(1_000, cause_mix={"none": 0.7, "carrier": 0.3})
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
    assert summary.upstream_share_of_late < 0.15
