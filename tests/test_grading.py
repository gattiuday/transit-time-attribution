"""Does the attribution recover a cause that was planted? Written before any claim.

The lesson this file exists to apply: a sibling repository shipped a simulator
that nothing graded, and when its own stated grading criterion was finally
pointed at it, it was wrong and had been from the start. So this file was
written before the README, and the generator plants the answer so there is
something to grade against.
"""

from __future__ import annotations

import dataclasses
from collections import Counter

import pytest
from conftest import EXPECTED_CAUSE

from tta.attribute import admissible_causes, attribute_log
from tta.config import LANES, next_departure
from tta.errors import AttributionError
from tta.generator import (
    DEPART_FLOOR_SECONDS,
    generate_log,
    label_is_true,
    lanes_by_name,
    verify_labels,
)
from tta.stages import Shipment


def _graded(convention: str, shipments: int = 2_000):
    log, truth = generate_log(shipments)
    _, rows = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, convention)
    return [(planted, row) for planted, row in zip(truth, rows, strict=True) if row.is_late]


def test_a_carrier_overrun_is_attributed_to_transit():
    graded = _graded("largest_cause")
    carrier = [row for planted, row in graded if planted == "carrier"]
    assert carrier
    assert all(row.cause == "transit" for row in carrier)


def test_a_missed_cutoff_is_attributed_upstream_of_the_scorecard_window():
    """The case a carrier scorecard is blind to by construction.

    This test demanded `release_to_depart` for every one of them, which stopped
    being true once the departure stopped being charged the overrun that caused
    the miss. On the three departure lane a release can overrun by five hours
    and miss a departure six hours out, leaving one hour the timetable added and
    five the warehouse did; `largest_cause` then names the warehouse, and it is
    right to. Six of two hundred and eleven land that way.

    Which upstream stage gets named is the convention. That the cause is
    upstream of ship confirm, and so outside a carrier scorecard's window, is
    the claim this repository actually makes, and it holds for all of them.
    """
    graded = _graded("largest_cause")
    missed = [row for planted, row in graded if planted == "missed_cutoff"]
    assert missed
    assert all(row.cause in ("order_to_release", "release_to_depart") for row in missed)
    assert not any(row.carrier_looks_late and row.cause == "transit" for row in missed)


def test_an_infeasible_plan_is_not_blamed_on_an_operation():
    """Late with no stage over plan is a planning failure, and naming a stage
    would blame an operation for arithmetic done before it started."""
    graded = _graded("largest_cause")
    infeasible = [row for planted, row in graded if planted == "infeasible_plan"]
    assert infeasible
    assert all(row.cause == "infeasible_plan" for row in infeasible)


def test_a_warehouse_overrun_is_attributed_to_the_warehouse_under_first_cause():
    """True by construction under this convention, and kept for the second half.

    `first_cause` returns the first stage in `STAGES` with a positive overrun
    and `order_to_release` is first, so for a planted warehouse overrun this
    assertion tests tuple ordering. An audit said so and it is right. What is
    not true by construction is that the same shipments are attributed upstream
    under the other convention as well, which is the claim the README makes, so
    that is asserted here too and it is the part that can fail.
    """
    warehouse = [row for planted, row in _graded("first_cause") if planted == "warehouse"]
    assert warehouse
    assert all(row.cause == "order_to_release" for row in warehouse)

    under_largest = {
        row.shipment_id: row.cause
        for planted, row in _graded("largest_cause")
        if planted == "warehouse"
    }
    assert all(
        under_largest[row.shipment_id] in ("order_to_release", "release_to_depart")
        for row in warehouse
    ), "a planted warehouse overrun was attributed outside the two upstream stages"


def test_no_shipment_planted_as_on_plan_is_reported_late():
    """A tautology against this generator, which is the reason to say so here.

    A `none` shipment is released on or before plan, runs under its committed
    transit, and carries a promise with positive slack, so arriving late is
    algebraically impossible. The assertion cannot fail, and an audit was right
    to call that out: a test whose docstring sells it as a guard that caught a
    real defect, against a generator that cannot produce the defect, is a test
    that only looks like evidence.

    It stays because the generator can change and the property is one a change
    could break. What makes it evidence is the mutation below: the same check is
    run against a shipment constructed to violate it, so the assertion is shown
    to be capable of failing even though the fixture never makes it fail.
    """
    graded = _graded("largest_cause")
    assert not [row for planted, row in graded if planted == "none"]

    # The same property, against a log that does violate it.
    lane = LANES[0]
    planned = 6 * 3600
    depart = next_departure(planned + DEPART_FLOOR_SECONDS, lane)
    committed = lane.committed_transit_days * 86_400
    late_but_on_plan = Shipment(
        shipment_id="SHP-LATE-ON-PLAN",
        lane=lane.name,
        order_created=0,
        released=planned,
        ship_confirm=depart,
        delivered=depart + committed,
        promised_delivery=depart + committed - 2 * 3600,
        planned_release=planned,
        committed_transit=committed,
    )
    summary, _ = attribute_log([late_but_on_plan], lanes_by_name(), DEPART_FLOOR_SECONDS)
    assert summary.late == 1
    assert label_is_true(late_but_on_plan, "none") == "delivered late"


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
    """The limit that survives the arithmetic being right.

    This test asserted a recovery band of 0.6 to 0.8 and passed, and the band
    was measuring a defect. The release overrun was charged twice, once as
    itself and once as the departure it pushed, which made a missed departure
    mechanically larger than the overrun that caused it, so `largest_cause` named
    the departure for all but a handful of the planted warehouse overruns.
    Netting the departure charge moved the recovery from 68.6% to 88.4% over
    twelve logs, so the ceiling this test was pinning was arithmetic, not
    structure. ADR-007 carries the measured figures; this docstring carried two
    that nothing in the repository produced, because `tests/` is outside the set
    of documents the number checker reads and a figure nobody checks drifts.

    What remains is real and smaller. On a lane with one departure a day a nine
    hour overrun still leaves fifteen hours of waiting that releasing on plan
    would have avoided, so `largest_cause` names the timetable rather than the
    warehouse. The two conventions disagree by about nineteen points, which is
    what ADR-007 and ADR-008 say. An earlier version of this docstring also gave
    a before figure for that spread; nothing in the repository measured
    `first_cause` under the old charge, so there is no before figure to give.

    And read `test_the_attribution_never_names_a_stage_that_did_not_overrun`
    before this test. Recovery here is agreement with an arbitrary label, not
    correctness. ADR-008.
    """
    for convention in ("first_cause", "largest_cause"):
        graded = _graded(convention)
        correct = sum(1 for planted, row in graded if EXPECTED_CAUSE[planted] == row.cause)
        assert 0.65 < correct / len(graded) < 1.0


def test_the_proportional_rule_names_the_same_cause_as_largest_cause():
    """Stated outright, because it was presented as a third opinion.

    `proportional` splits the lateness across every stage over plan, and its
    `cause` field is whichever stage holds the largest share, which is the
    definition of `largest_cause`. The two therefore agree on every shipment by
    construction. An audit found Claim 3's table publishing them as two rows
    with identical recovery and reading as corroboration between independent
    rules, when it was one rule printed twice.

    So there are two conventions for naming a cause and one rule for splitting
    one. This test exists to keep that stated rather than discovered.
    """
    largest = {row.shipment_id: row.cause for _, row in _graded("largest_cause")}
    proportional = {row.shipment_id: row.cause for _, row in _graded("proportional")}
    assert largest == proportional


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


# --------------------------------------------------------------------------
# The ground truth grades the tool, so something has to grade the ground truth.
# --------------------------------------------------------------------------


def test_every_planted_label_is_true_of_the_log_it_describes(log, truth):
    """The check that four false label classes would each have failed.

    Three were found by a confusion matrix and one by writing this check. All
    four were the label being wrong while the attribution was right, which is
    the failure mode a grader cannot see from the inside: a wrong label makes a
    correct attribution look like an error and the natural response is to change
    the attribution.
    """
    wrong = [
        (shipment.shipment_id, cause, reason)
        for shipment, cause in zip(log, truth, strict=True)
        if (reason := label_is_true(shipment, cause)) is not None
    ]
    assert not wrong, f"{len(wrong)} planted labels are false: {wrong[:5]}"


def test_every_shipment_planted_as_a_missed_cutoff_really_missed_a_departure(log, truth, lanes):
    """The defect this file's own test could not see.

    `test_a_missed_cutoff_is_attributed_to_the_departure_wait` grades only late
    shipments, and the mislabelled ones were not late, so it passed while 35 of
    272 `missed_cutoff` labels described a shipment that released one minute
    late and missed nothing. This asserts the label over the whole group rather
    than over the part of it the grading happens to look at.
    """
    labelled = [
        shipment for shipment, cause in zip(log, truth, strict=True) if cause == "missed_cutoff"
    ]
    assert labelled
    for shipment in labelled:
        lane = lanes[shipment.lane]
        on_plan_depart = next_departure(shipment.planned_release + DEPART_FLOOR_SECONDS, lane)
        assert shipment.ship_confirm > on_plan_depart, (
            f"{shipment.shipment_id} is labelled missed_cutoff and left on the departure "
            "an on plan release would have caught"
        )


def test_the_generator_refuses_to_return_a_log_with_a_false_label(log, truth):
    """The verifier has to be able to fail, or it is decoration."""
    corrupted = list(truth)
    on_time = next(
        index
        for index, (shipment, cause) in enumerate(zip(log, truth, strict=True))
        if cause == "none"
    )
    corrupted[on_time] = "carrier"
    with pytest.raises(AttributionError, match="planted labels are false"):
        verify_labels(log, corrupted)


@pytest.mark.parametrize(
    ("cause", "mutate", "reason"),
    [
        ("none", {"released": "late"}, "a stage ran over its plan"),
        ("warehouse", {"released": "early"}, "the release did not overrun"),
        ("missed_cutoff", {"released": "early"}, "the release did not overrun"),
        ("missed_cutoff", {"ship_confirm": "on_plan"}, "no departure was missed"),
        ("carrier", {"delivered": "early"}, "the transit did not overrun"),
        ("carrier", {"released": "late"}, "an upstream stage ran over its plan too"),
        ("infeasible_plan", {"promised_delivery": "generous"}, "the plan did reach the promise"),
        ("infeasible_plan", {"released": "late"}, "a stage ran over its plan"),
    ],
)
def test_every_reason_a_label_can_be_false_is_detected(one_lane, handling, cause, mutate, reason):
    """Each branch of the label check, exercised by breaking the thing it checks.

    A verifier whose failure branches are never executed is a verifier that has
    only been seen to pass, which is the position the three earlier false labels
    were found from.
    """
    planned = 6 * 3600
    on_plan_depart = next_departure(planned + handling, one_lane)
    committed = one_lane.committed_transit_days * 86_400
    shipment = Shipment(
        shipment_id="SHP-PROBE",
        lane=one_lane.name,
        order_created=0,
        released=planned,
        ship_confirm=on_plan_depart,
        delivered=on_plan_depart + committed,
        promised_delivery=on_plan_depart + committed + 3600,
        planned_release=planned,
        committed_transit=committed,
    )
    if cause in ("warehouse", "missed_cutoff", "carrier", "infeasible_plan"):
        # Start from a shipment the label is true of, then break one thing.
        if cause in ("warehouse", "missed_cutoff"):
            released = next_departure(planned + handling, one_lane) - handling + 60
            shipment = dataclasses.replace(
                shipment,
                released=released,
                ship_confirm=next_departure(released + handling, one_lane),
                delivered=next_departure(released + handling, one_lane) + committed,
            )
        if cause == "carrier":
            shipment = dataclasses.replace(shipment, delivered=shipment.delivered + 2 * 3600)
        if cause == "infeasible_plan":
            shipment = dataclasses.replace(
                shipment, promised_delivery=on_plan_depart + committed - 3600
            )
        assert label_is_true(shipment, cause) is None

    field, how = next(iter(mutate.items()))
    if field == "delivered" and how == "early":
        shipment = dataclasses.replace(
            shipment, delivered=shipment.ship_confirm + shipment.committed_transit - 600
        )
    elif how == "late":
        shipment = dataclasses.replace(shipment, released=shipment.planned_release + 7200)
    elif how == "early":
        shipment = dataclasses.replace(shipment, released=shipment.planned_release - 600)
    elif how == "on_plan":
        shipment = dataclasses.replace(shipment, ship_confirm=on_plan_depart)
    elif how == "generous":
        shipment = dataclasses.replace(
            shipment, promised_delivery=on_plan_depart + committed + 86_400
        )
    else:  # pragma: no cover - the parametrisation above covers every branch
        raise AssertionError(how)
    assert label_is_true(shipment, cause) == reason, field


def test_a_shipment_labelled_on_plan_that_arrives_late_is_a_false_label(one_lane, handling):
    """The one `none` branch the generator cannot reach, which is the point.

    A `none` shipment from this generator carries a promise with slack, so it
    cannot be late with every stage inside its plan. `label_is_true` is applied
    to whatever log it is given, though, and a log whose promises were set
    somewhere else can contain exactly that: nothing over plan and a late
    arrival, which is an infeasible plan mislabelled as nothing wrong.
    """
    planned = 6 * 3600
    depart = next_departure(planned + handling, one_lane)
    committed = one_lane.committed_transit_days * 86_400
    shipment = Shipment(
        shipment_id="SHP-PROBE",
        lane=one_lane.name,
        order_created=0,
        released=planned,
        ship_confirm=depart,
        delivered=depart + committed,
        promised_delivery=depart + committed - 2 * 3600,
        planned_release=planned,
        committed_transit=committed,
    )
    assert label_is_true(shipment, "none") == "delivered late"
    assert label_is_true(shipment, "infeasible_plan") is None


# --------------------------------------------------------------------------
# Admissibility: whether the named cause is true of the shipment at all.
#
# Recovery against a planted label measures agreement with a choice the
# generator made between simultaneously true statements. Both labels are true of
# 96.2% of the late deliveries carrying either, measured over twelve logs by
# `experiments/exp01`, and `label_is_true` passes both, because both are true.
# ADR-008.
# --------------------------------------------------------------------------


def test_the_attribution_never_names_a_stage_that_did_not_overrun(log, lanes):
    """The property that is about the attribution rather than about the label.

    Under every convention, on every late delivery. If this ever fails the tool
    is inventing a cause, which is a different and much worse failure than
    naming the other true one.
    """
    for convention in ("first_cause", "largest_cause", "proportional"):
        _, rows = attribute_log(log, lanes, DEPART_FLOOR_SECONDS, convention)
        for shipment, row in zip(log, rows, strict=True):
            if not row.is_late:
                continue
            allowed = admissible_causes(shipment, lanes[shipment.lane], DEPART_FLOOR_SECONDS)
            assert row.cause in allowed, (
                f"{convention} named {row.cause} on {shipment.shipment_id}, which is true of "
                f"nothing that happened to it; admissible were {sorted(allowed)}"
            )


def test_the_two_upstream_labels_are_usually_both_true_of_the_same_shipment(log, truth, lanes):
    """The measurement that makes the recovery rate uninterpretable on its own.

    If this were small, recovery against the planted label would be close to a
    statement about the attribution. It is not small.
    """
    upstream = [
        shipment
        for shipment, cause in zip(log, truth, strict=True)
        if cause in ("warehouse", "missed_cutoff")
    ]
    assert upstream
    both = [
        shipment
        for shipment in upstream
        if {"order_to_release", "release_to_depart"}
        <= admissible_causes(shipment, lanes[shipment.lane], DEPART_FLOOR_SECONDS)
    ]
    assert len(both) / len(upstream) > 0.9, (
        "the two upstream labels have stopped overlapping, which would make the recovery "
        "rate meaningful again and this repository's account of it wrong"
    )


def test_a_shipment_on_plan_is_admissible_only_as_not_late(one_lane, handling):
    """The boundary cases of admissibility, which the fixture does not exercise."""
    planned = 6 * 3600
    depart = next_departure(planned + handling, one_lane)
    committed = one_lane.committed_transit_days * 86_400
    on_plan = Shipment(
        shipment_id="SHP-CLEAN",
        lane=one_lane.name,
        order_created=0,
        released=planned,
        ship_confirm=depart,
        delivered=depart + committed,
        promised_delivery=depart + committed + 3600,
        planned_release=planned,
        committed_transit=committed,
    )
    assert admissible_causes(on_plan, one_lane, handling) == {"not_late"}

    infeasible = dataclasses.replace(on_plan, promised_delivery=depart + committed - 2 * 3600)
    assert admissible_causes(infeasible, one_lane, handling) == {"infeasible_plan"}

    carrier = dataclasses.replace(on_plan, delivered=on_plan.delivered + 2 * 86_400)
    assert admissible_causes(carrier, one_lane, handling) == {"transit"}
