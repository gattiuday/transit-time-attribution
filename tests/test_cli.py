"""Exit codes, because the distinction between "no" and "cannot say" is the contract."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from tta.cli import (
    EXIT_CANNOT_ANSWER,
    EXIT_OK,
    EXIT_SCORECARD_BLIND,
    EXIT_USAGE,
    main,
)
from tta.errors import AttributionError, UnattributableShipment


def test_generate_writes_a_log_and_exits_zero(tmp_path, capsys):
    out = tmp_path / "log.csv"
    assert main(["generate", "--out", str(out), "--shipments", "300"]) == EXIT_OK
    assert out.exists()
    assert "300 shipments" in capsys.readouterr().out


def test_generate_writes_the_planted_causes_when_asked(tmp_path):
    out, truth = tmp_path / "log.csv", tmp_path / "truth.csv"
    main(["generate", "--out", str(out), "--truth", str(truth), "--shipments", "300"])
    assert set(pd.read_csv(truth).columns) == {"shipment_id", "planted_cause"}


def test_generate_creates_missing_parent_directories(tmp_path):
    out = tmp_path / "deep" / "er" / "log.csv"
    assert main(["generate", "--out", str(out), "--shipments", "250"]) == EXIT_OK
    assert out.exists()


def test_attribute_on_the_fixture_reports_a_blind_scorecard(capsys):
    assert main(["attribute"]) == EXIT_SCORECARD_BLIND
    out = capsys.readouterr().out
    assert "VERDICT: scorecard_misses_most_lateness" in out


def test_attribute_prints_the_cause_table_with_the_scorecard_window_marked(capsys):
    main(["attribute"])
    out = capsys.readouterr().out
    assert "scorecard" in out
    assert "outside" in out
    assert "inside" in out


def test_attribute_reads_a_csv_log(tmp_path):
    out = tmp_path / "log.csv"
    main(["generate", "--out", str(out), "--shipments", "400"])
    assert main(["attribute", "--log", str(out)]) in (EXIT_OK, EXIT_SCORECARD_BLIND)


@pytest.mark.parametrize("convention", ["first_cause", "largest_cause", "proportional"])
def test_attribute_accepts_every_convention(convention):
    assert main(["attribute", "--convention", convention]) in (
        EXIT_OK,
        EXIT_SCORECARD_BLIND,
    )


@pytest.mark.parametrize("granularity", ["minute", "quarter_hour", "hour", "day"])
def test_attribute_accepts_every_granularity(granularity):
    assert main(["attribute", "--granularity", granularity]) in (
        EXIT_OK,
        EXIT_SCORECARD_BLIND,
    )


def test_attribute_writes_a_json_result_when_asked(tmp_path):
    target = tmp_path / "out" / "result.json"
    main(["attribute", "--json", str(target)])
    payload = json.loads(target.read_text())
    assert {"summary", "upstream_share_of_late", "verdict", "attributions"} <= set(payload)


def test_a_log_missing_columns_cannot_be_answered(tmp_path, capsys):
    pd.DataFrame({"shipment_id": ["A"] * 300}).to_csv(tmp_path / "bad.csv", index=False)
    assert main(["attribute", "--log", str(tmp_path / "bad.csv")]) == EXIT_CANNOT_ANSWER
    assert "cannot answer:" in capsys.readouterr().err


def test_a_log_with_non_numeric_timestamps_cannot_be_answered(tmp_path):
    out = tmp_path / "log.csv"
    main(["generate", "--out", str(out), "--shipments", "300"])
    frame = pd.read_csv(out)
    frame["delivered"] = frame["delivered"].astype(object)
    frame.loc[0, "delivered"] = "tuesday"
    frame.to_csv(out, index=False)
    assert main(["attribute", "--log", str(out)]) == EXIT_CANNOT_ANSWER


def test_too_few_shipments_cannot_be_answered(tmp_path):
    out = tmp_path / "log.csv"
    main(["generate", "--out", str(out), "--shipments", "20"])
    assert main(["attribute", "--log", str(out)]) == EXIT_CANNOT_ANSWER


def test_a_log_with_out_of_order_timestamps_cannot_be_answered(tmp_path):
    out = tmp_path / "log.csv"
    main(["generate", "--out", str(out), "--shipments", "300"])
    frame = pd.read_csv(out)
    frame.loc[0, "delivered"] = frame.loc[0, "ship_confirm"] - 1
    frame.to_csv(out, index=False)
    assert main(["attribute", "--log", str(out)]) == EXIT_CANNOT_ANSWER


def test_a_missing_log_file_is_a_usage_error(tmp_path, capsys):
    assert main(["attribute", "--log", str(tmp_path / "absent.csv")]) == EXIT_USAGE
    assert "usage error:" in capsys.readouterr().err


def test_an_unattributable_shipment_is_a_cannot_answer_not_a_usage_error():
    """UnattributableShipment subclasses both AttributionError and ValueError, so
    the order of the handlers in `main` decides which code it gets. Pinned rather
    than left to the reader of the except clauses."""
    assert issubclass(UnattributableShipment, ValueError)
    assert issubclass(UnattributableShipment, AttributionError)

    import tta.cli as cli

    original = cli._run_resolution
    cli._run_resolution = lambda _args: (_ for _ in ()).throw(
        UnattributableShipment("delivered before ship_confirm")
    )
    try:
        assert main(["resolution"]) == EXIT_CANNOT_ANSWER
    finally:
        cli._run_resolution = original


def test_resolution_reports_the_floor_and_the_granularity_cost(capsys):
    assert main(["resolution"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "smallest rate this sample can distinguish" in out
    assert "granularity leaves" in out


def test_resolution_reports_the_sample_needed_for_an_unsupportable_claim(capsys):
    main(["resolution", "--claim", "0.906"])
    out = capsys.readouterr().out
    assert "cannot tell the two apart" in out or "can tell the two apart" in out


def test_an_unknown_subcommand_is_a_usage_error():
    assert main(["blame-everyone"]) == EXIT_USAGE


def test_no_subcommand_is_a_usage_error():
    assert main([]) == EXIT_USAGE


def test_help_exits_cleanly():
    assert main(["--help"]) == EXIT_OK


def test_an_unknown_convention_is_rejected_as_a_usage_error():
    assert main(["attribute", "--convention", "blame_carrier"]) == EXIT_USAGE


def test_a_sound_scorecard_exits_zero(tmp_path):
    """A log whose lateness is almost all transit is one a scorecard measures
    correctly, and the tool says so rather than always finding a problem."""
    from tta.generator import generate_log

    log, _ = generate_log(600, cause_mix={"none": 0.7, "carrier": 0.3})
    frame = pd.DataFrame([shipment.as_dict() for shipment in log])
    path = tmp_path / "carrier-only.csv"
    frame.to_csv(path, index=False)
    assert main(["attribute", "--log", str(path)]) == EXIT_OK


def test_every_exit_code_has_a_distinct_value():
    assert {EXIT_OK, EXIT_SCORECARD_BLIND, EXIT_CANNOT_ANSWER, EXIT_USAGE} == {0, 1, 2, 3}
