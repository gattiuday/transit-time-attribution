"""The verdict policy, and the two warnings that matter most."""

from __future__ import annotations

import dataclasses

from tta.attribute import attribute_log
from tta.config import Thresholds
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.report import SCORECARD_BLIND, SCORECARD_SOUND, judge, render_causes


def _summary(**kwargs):
    log, _ = generate_log(kwargs.pop("shipments", 1_000), **kwargs)
    return attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)[0]


def test_a_blind_scorecard_is_reported_as_such(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    verdict = judge(summary)
    assert verdict.status == SCORECARD_BLIND
    assert verdict.exit_code == 1


def test_a_blind_verdict_names_the_shipments_recorded_as_a_carrier_success(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    assert any("carrier success" in reason for reason in judge(summary).reasons)


def test_a_sound_scorecard_is_reported_as_such():
    """The control case, so the verdict is not simply always the same."""
    summary = _summary(cause_mix={"none": 0.7, "carrier": 0.3})
    verdict = judge(summary)
    assert verdict.status == SCORECARD_SOUND
    assert verdict.exit_code == 0


def test_a_sound_verdict_still_states_its_reasons():
    verdict = judge(_summary(cause_mix={"none": 0.7, "carrier": 0.3}))
    assert verdict.reasons


def test_the_material_share_is_configurable_rather_than_hard_coded(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    strict = judge(summary, Thresholds(material_share=0.15))
    lenient = judge(summary, Thresholds(material_share=0.95))
    assert strict.status == SCORECARD_BLIND
    assert lenient.status == SCORECARD_SOUND


def test_a_precise_but_blind_scorecard_is_warned_about(log, lanes, handling):
    """The harder failure to notice: a metric that is rarely wrong about what it
    flags reads as trustworthy."""
    summary, _ = attribute_log(log, lanes, handling)
    assert any("reads as trustworthy" in warning for warning in judge(summary).warnings)


def test_a_small_sample_is_warned_about(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    shrunk = dataclasses.replace(summary, shipments=50)
    assert any("below the minimum" in warning for warning in judge(shrunk).warnings)


def test_overlapping_causes_are_warned_about_with_the_convention_named(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    warnings = judge(summary).warnings
    assert any("depends on the convention" in warning for warning in warnings)
    assert any(summary.convention in warning for warning in warnings)


def test_the_cause_table_marks_which_stage_the_scorecard_can_see(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    table = render_causes(summary)
    assert "inside" in table
    assert "outside" in table


def test_the_cause_table_shares_sum_to_one(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    table = render_causes(summary)
    assert "100.0%" in table


def test_the_cause_table_reports_the_upstream_share(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    assert "of which upstream" in render_causes(summary)


def test_the_cause_table_lists_causes_largest_first(log, lanes, handling):
    summary, _ = attribute_log(log, lanes, handling)
    rows = render_causes(summary).splitlines()[2:-3]
    counts = [int(row.split()[1]) for row in rows]
    assert counts == sorted(counts, reverse=True)
