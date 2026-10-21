"""Re-measure every published figure and write docs/metrics.json.

No figure here is transcribed by hand. Values come from the test suite's
machine readable reports, from the experiments' JSON, from the committed fixture
read back off disk, or from the project's own configuration. A sibling
repository hardcoded thirteen of its declared constants, which made its own
claim false and made each one a guard that could not notice the thing it was
guarding change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "docs" / "experiments"
GENERATED_DIR = ROOT / "docs" / "generated"
METRICS_PATH = ROOT / "docs" / "metrics.json"
JUNIT_PATH = ROOT / "junit.xml"
COVERAGE_PATH = ROOT / "coverage.json"

EXPERIMENTS = (
    "exp01_recovery",
    "exp02_scorecard_blindness",
    "exp03_cutoff_amplification",
    "exp04_clock_granularity",
    "exp05_resolution_floor",
)

ANCHORS: dict[str, list[str]] = {
    "tests_total": ["{} tests"],
    "coverage_line_pct": [
        "{}% line coverage",
        "{}% over eleven",
        "that cannot tell {}% from 75%.",
        "{}% from 95%,",
        "measured precision of {}%, and a sample",
    ],
    "upstream_share_pct": [
        "{}% of late deliveries",
        "The {}% upstream",
        "not from the data. The {}% upstream share",
        "is general. That it is {}% is a fact about",
        "that transfer. The {}% upstream share",
    ],
    "upstream_share_sd": ["sd of {} points"],
    "scorecard_precision_pct": [
        "{}% of the time",
        "right {}% of the time",
        "The scorecard's {}% precision and",
        "precision of {}% and",
    ],
    "scorecard_recall_pct": [
        "sees {}%",
        "{}% of them",
        "92.6% precision and {}% recall. The",
        "and {}% recall",
    ],
    "invisible_share_pct": [
        "{}% arrive with the carrier",
        "The {}% upstream",
        "not from the data. The {}% upstream share",
        "is general. That it is {}% is a fact about",
        "that transfer. The {}% upstream share",
    ],
    "multiple_cause_share_pct": ["{}% of late deliveries have"],
    "convention_spread_points": ["spread across conventions measures {} points"],
    "best_recovery_pct": ["recovers {}%", "first_cause | {}% | missed"],
    "worst_recovery_pct": [
        "down to {}%",
        "proportional | {}% | the same as",
        "largest_cause | {}% | warehouse",
    ],
    "single_departure_late_pct": ["{}% late on"],
    "multi_departure_late_pct": [
        "against {}% on",
        "service against {}% on the three",
        "{}% late against",
        "against {}% on the three",
        "{}% on the three",
    ],
    "single_departure_carrier_share_pct": ["{}% of its own lateness"],
    "multi_departure_carrier_share_pct": [
        "{}% on the lane with three",
        "of its own lateness, {}% against 24%. A",
    ],
    "daily_clock_late_loss_pct": ["loses {}% of"],
    "daily_clock_mode_swing_pct": ["swings the count by {}%", "75.5%. That is a {}% difference in"],
    "hourly_clock_shift_points": ["shifts it by {} points"],
    "resolution_floor_small_pct": ["floor of {}%"],
    "flagged_at_small_sample": ["flags {} shipments", "A rate over {} flagged"],
    "smallest_supporting_sample": [
        "about {} shipments",
        "needs about {} shipments",
        "needs about {} shipments to resolve",
        "needs about {} shipments to separate",
    ],
    "fixture_shipments": ["{} shipments"],
    "fixture_lanes": ["{} lanes"],
    "python_min_version": ["Python {} or newer. No API", "Python {}+ | everything |"],
    "experiment_shipments": ["logs of {} shipments"],
    "small_sample_shipments": ["In a {} shipment sample", "At {} shipments the"],
    "infeasible_plan_share_pct": ["plans are {}% of", "{}% of the late"],
    "daily_floor_late": ["two choices produce {} and 970 late"],
    "daily_nearest_late": ["produce 631 and {} late shipments"],
    "daily_floor_upstream_pct": ["an upstream share of {}% against 75.5%."],
    "daily_nearest_upstream_pct": ["share of 63.9% against {}%. That is a 54%"],
    "single_lane_worst_late_pct": ["late against 36.4% and {}%. The mechanism"],
    "carrier_rate_spread_points": ["spread of {} points"],
    "single_lane_best_late_pct": [
        "{}% on the three",
        "against {}% on the lane with three",
        "shows {}% on the three",
    ],
}

FORMATS: dict[str, str] = {
    "coverage_line_pct": "{:.0f}",
    "upstream_share_pct": "{:.1f}",
    "upstream_share_sd": "{:.2f}",
    "scorecard_precision_pct": "{:.1f}",
    "scorecard_recall_pct": "{:.1f}",
    "invisible_share_pct": "{:.1f}",
    "multiple_cause_share_pct": "{:.1f}",
    "convention_spread_points": "{:.1f}",
    "best_recovery_pct": "{:.1f}",
    "worst_recovery_pct": "{:.1f}",
    "single_departure_late_pct": "{:.1f}",
    "multi_departure_late_pct": "{:.1f}",
    "single_departure_carrier_share_pct": "{:.1f}",
    "multi_departure_carrier_share_pct": "{:.1f}",
    "daily_clock_late_loss_pct": "{:.0f}",
    "daily_clock_mode_swing_pct": "{:.0f}",
    "hourly_clock_shift_points": "{:.2f}",
    "resolution_floor_small_pct": "{:.2f}",
    "flagged_at_small_sample": "{:.0f}",
    "infeasible_plan_share_pct": "{:.1f}",
    "single_lane_worst_late_pct": "{:.1f}",
    "single_lane_best_late_pct": "{:.1f}",
    "carrier_rate_spread_points": "{:.1f}",
    "daily_floor_upstream_pct": "{:.1f}",
    "daily_nearest_upstream_pct": "{:.1f}",
    "daily_floor_late": "{:.0f}",
    "daily_nearest_late": "{:.0f}",
    "experiment_shipments": "{:,.0f}",
    "python_min_version": "{:.2f}",
}

#: Every document that quotes a measured figure, which is more than the prose.
#: Source modules and experiment code are checked too, reduced to their
#: docstrings: a sibling repository found four reversed claims surviving in
#: exactly the files its checker did not read.
CHECKED_DOCUMENTS = (
    "README.md",
    "docs/defense-guide.md",
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "docs" / "adr").glob("ADR-*.md")),
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "src" / "tta").glob("*.py")),
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "experiments").glob("exp*.py")),
)


def run_tests() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-q",
            f"--junitxml={JUNIT_PATH}",
            "--cov=tta",
            "--cov-report=json",
        ],
        cwd=ROOT,
        check=True,
    )


def run_experiments() -> None:
    env_path = f"{ROOT / 'src'}:{ROOT / 'experiments'}:{ROOT / 'tests'}"
    for name in EXPERIMENTS:
        subprocess.run(
            [sys.executable, str(ROOT / "experiments" / f"{name}.py")],
            cwd=ROOT,
            check=True,
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )


#: The one test file whose failure cannot block collection. Its tests read
#: ``docs/metrics.json`` and assert that every published figure is anchored, so
#: they are red by construction whenever the figures are stale, which is the
#: state collection exists to fix. Blocking on them deadlocks: the file cannot
#: be written until the tests pass and the tests cannot pass until it is
#: written. Every other failure still refuses, and ``make verify`` runs the full
#: suite *after* collection, so a real receipts regression still fails the
#: build. It just no longer stops the file that would clear it from being
#: written. See ADR-006.
RECEIPTS_SUITE = "tests/test_check_numbers.py"


def failing_tests(suite: ElementTree.Element) -> list[str]:
    """Names of the tests that failed or errored, as ``file::test``."""
    failures = []
    for case in suite.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        path = (case.get("classname") or "").split(".")
        name = case.get("name") or "?"
        failures.append(f"{'/'.join(path)}.py::{name}" if path else name)
    return failures


def read_suite() -> dict[str, float]:
    suite = ElementTree.parse(JUNIT_PATH).getroot()
    if suite.tag != "testsuite":
        suite = suite.find("testsuite")
    failures = failing_tests(suite)
    blocking = [name for name in failures if not name.startswith(RECEIPTS_SUITE)]
    if blocking:
        raise SystemExit(
            f"refusing to publish metrics from a run with {len(blocking)} failing "
            f"tests outside {RECEIPTS_SUITE}: {', '.join(sorted(blocking))}"
        )
    if failures:
        print(
            f"warning: {len(failures)} receipts tests are red, which is expected "
            "while the figures are stale. Re-run the suite after this collection "
            "and treat a remaining failure as real",
            file=sys.stderr,
        )
    coverage = json.loads(COVERAGE_PATH.read_text())
    return {
        "tests_total": int(suite.get("tests")),
        "coverage_line_pct": float(coverage["totals"]["percent_covered"]),
    }


def read_experiment(name: str) -> dict:
    return json.loads((EXPERIMENT_DIR / f"{name}.json").read_text())


def _fixture_cause_share(cause: str) -> float:
    """Share of the committed fixture's late deliveries with a given cause.

    Read from the fixture rather than typed, so a regenerated log moves the
    metric and the documents quoting it fail the check together.
    """
    from tta.attribute import attribute_log
    from tta.generator import DEPART_FLOOR_SECONDS, lanes_by_name
    from tta.stages import Shipment

    frame = pd.read_csv(ROOT / "data" / "fixtures" / "event-log.csv")
    log = [Shipment(**row) for row in frame.to_dict("records")]
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
    return summary.causes.get(cause, 0) / summary.late


def derive() -> dict[str, float]:
    recovery = read_experiment("exp01_recovery")
    blind = read_experiment("exp02_scorecard_blindness")
    cutoff = read_experiment("exp03_cutoff_amplification")
    clock = read_experiment("exp04_clock_granularity")
    floor = read_experiment("exp05_resolution_floor")

    measures = blind["measures"]
    fixture = pd.read_csv(ROOT / "data" / "fixtures" / "event-log.csv")
    requires = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["requires-python"]

    def clock_row(granularity: str, mode: str) -> dict:
        return next(
            row
            for row in clock["series"]
            if row["granularity"] == granularity and row["mode"] == mode
        )

    daily_floor = clock_row("day", "floor")["late_mean"]
    daily_nearest = clock_row("day", "nearest")["late_mean"]

    metrics = dict(read_suite())
    metrics.update(
        {
            "upstream_share_pct": measures["upstream share of late deliveries"]["mean"] * 100,
            "upstream_share_sd": measures["upstream share of late deliveries"]["sd"] * 100,
            "scorecard_precision_pct": measures["scorecard precision, of what it flags"]["mean"]
            * 100,
            "scorecard_recall_pct": measures["scorecard recall, of all late deliveries"]["mean"]
            * 100,
            "invisible_share_pct": measures["late with the carrier inside its window"]["mean"]
            * 100,
            "multiple_cause_share_pct": measures["late with more than one stage over plan"]["mean"]
            * 100,
            "convention_spread_points": blind["upstream_share_convention_spread"] * 100,
            "best_recovery_pct": recovery["best_recovery_mean"] * 100,
            "worst_recovery_pct": recovery["worst_recovery_mean"] * 100,
            "single_departure_late_pct": cutoff["single_departure_late_rate"] * 100,
            "multi_departure_late_pct": cutoff["multi_departure_late_rate"] * 100,
            "single_departure_carrier_share_pct": cutoff["single_departure_carrier_share"] * 100,
            "multi_departure_carrier_share_pct": cutoff["multi_departure_carrier_share"] * 100,
            "daily_clock_late_loss_pct": clock["late_lost_to_daily_clock_share"] * 100,
            "daily_clock_mode_swing_pct": (daily_nearest - daily_floor) / daily_floor * 100,
            "hourly_clock_shift_points": clock["upstream_share_shift_at_hourly_points"],
            "resolution_floor_small_pct": floor["floor_at_smallest_sample"] * 100,
            "flagged_at_small_sample": floor["flagged_at_smallest_sample"],
            "smallest_supporting_sample": floor["smallest_sample_supporting_the_claim"],
            "infeasible_plan_share_pct": _fixture_cause_share("infeasible_plan") * 100,
            "single_lane_worst_late_pct": max(
                value["late_rate"]["mean"] for value in cutoff["per_lane"].values()
            )
            * 100,
            "single_lane_best_late_pct": min(
                value["late_rate"]["mean"] for value in cutoff["per_lane"].values()
            )
            * 100,
            "carrier_rate_spread_points": (
                max(value["carrier_rate"]["mean"] for value in cutoff["per_lane"].values())
                - min(value["carrier_rate"]["mean"] for value in cutoff["per_lane"].values())
            )
            * 100,
            "daily_floor_late": clock_row("day", "floor")["late_mean"],
            "daily_nearest_late": clock_row("day", "nearest")["late_mean"],
            "daily_floor_upstream_pct": clock_row("day", "floor")["upstream_share_mean"] * 100,
            "daily_nearest_upstream_pct": clock_row("day", "nearest")["upstream_share_mean"] * 100,
            "small_sample_shipments": floor["series"][0]["shipments"],
            "experiment_shipments": recovery["shipments_per_log"],
            "fixture_shipments": len(fixture),
            "fixture_lanes": int(fixture["lane"].nunique()),
            "python_min_version": float(requires.lstrip(">=~^ ")),
        }
    )
    return metrics


def render_cause_block() -> str:
    """The README's cause table, rendered from the committed fixture."""
    from tta.attribute import attribute_log
    from tta.generator import DEPART_FLOOR_SECONDS, lanes_by_name
    from tta.report import render_causes
    from tta.stages import Shipment

    frame = pd.read_csv(ROOT / "data" / "fixtures" / "event-log.csv")
    log = [Shipment(**row) for row in frame.to_dict("records")]
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
    return render_causes(summary)


def render_lane_block() -> str:
    """The README's lane table, rendered from exp03's measured values."""
    cutoff = read_experiment("exp03_cutoff_amplification")
    lines = [
        "| Lane | Departures a day | A missed cutoff costs | Delivered late | "
        "Carrier caused | Carrier share of its lateness |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, value in cutoff["per_lane"].items():
        lines.append(
            f"| {name} | {value['departures_per_day']} | "
            f"{value['worst_missed_cutoff_cost_hours']:.0f} hours | "
            f"{value['late_rate']['mean'] * 100:.1f}% | "
            f"{value['carrier_rate']['mean'] * 100:.1f}% | "
            f"{value['carrier_share_of_late']['mean'] * 100:.1f}% |"
        )
    return "\n".join(lines)


def render_clock_block() -> str:
    """The README's clock table, rendered from exp04's measured values."""
    clock = read_experiment("exp04_clock_granularity")
    lines = [
        "| Clock | Rounding | Late deliveries | Upstream share |",
        "| --- | --- | --- | --- |",
    ]
    for row in clock["series"]:
        lines.append(
            f"| {row['granularity']} | {row['mode']} | {row['late_mean']:.0f} | "
            f"{row['upstream_share_mean'] * 100:.1f}% |"
        )
    return "\n".join(lines)


def render_convention_block() -> str:
    """The README's convention table, rendered from exp01's measured values."""
    recovery = read_experiment("exp01_recovery")
    lines = [
        "| Convention | Recovers the planted cause | Loses most on |",
        "| --- | --- | --- |",
    ]
    for name, value in recovery["per_convention"].items():
        lines.append(
            f"| {name} | {value['recovery_mean'] * 100:.1f}% | "
            f"{recovery['worst_group_per_convention'][name]} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-experiments", action="store_true")
    args = parser.parse_args()

    if not args.skip_tests:
        run_tests()
    if not args.skip_experiments:
        run_experiments()

    metrics = derive()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    blocks = {
        "cause-table.txt": render_cause_block(),
        "lane-table.md": render_lane_block(),
        "clock-table.md": render_clock_block(),
        "convention-table.md": render_convention_block(),
    }
    for name, body in blocks.items():
        (GENERATED_DIR / name).write_text(body + "\n")

    formatted = {name: FORMATS.get(name, "{}").format(value) for name, value in metrics.items()}
    METRICS_PATH.write_text(
        json.dumps(
            {
                "metrics": metrics,
                "formatted": formatted,
                "anchors": ANCHORS,
                "formats": FORMATS,
                "checked_documents": list(CHECKED_DOCUMENTS),
                "generated_blocks": {
                    "README.md": list(blocks),
                },
                "badge_only": ["python_min_version"],
                "note": (
                    "every value here is read from a run: the test suite, the "
                    "experiments, the committed fixture, or the project's own "
                    "configuration. No figure is transcribed by hand"
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {METRICS_PATH.relative_to(ROOT)} with {len(metrics)} metrics")
    for name in sorted(metrics):
        print(f"  {name:38s} {formatted[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
