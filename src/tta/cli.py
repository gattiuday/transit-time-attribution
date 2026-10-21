"""Command line entry point, with exit codes that distinguish "no" from "cannot say".

    0  the scorecard is measuring most of the lateness that happened
    1  the analysis ran and the answer was no: it misses a material share
    2  the analysis could not be run on this log
    3  usage error

1 and 2 are kept apart because a transport team wiring this into a carrier
review needs to read the report on 1 and fix the data on 2. The distinction is
carried by the exception type rather than inferred from the exception class, so
`UnattributableShipment` subclasses both `AttributionError` and `ValueError`
and the handler reads the author's intent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tta.attribute import attribute_log
from tta.config import CONVENTIONS, DEFAULTS, GRANULARITIES, LANES
from tta.errors import AttributionError
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.report import judge, render_causes
from tta.resolution import coarsen, rate_with_floor
from tta.stages import Shipment

EXIT_OK = 0
EXIT_SCORECARD_BLIND = 1
EXIT_CANNOT_ANSWER = 2
EXIT_USAGE = 3

COLUMNS = (
    "shipment_id",
    "lane",
    "order_created",
    "released",
    "ship_confirm",
    "delivered",
    "promised_delivery",
    "planned_release",
    "committed_transit",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tta",
        description=(
            "Attribute late deliveries to the stage that caused them, including the "
            "stages a carrier scorecard cannot see."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="write a seeded event log to CSV")
    gen.add_argument("--out", required=True, type=Path)
    gen.add_argument("--shipments", type=int, default=2_000)
    gen.add_argument("--seed", type=int, default=20261021)
    gen.add_argument("--truth", type=Path, default=None, help="also write the planted causes here")

    att = sub.add_parser("attribute", help="attribute an event log and judge the scorecard")
    att.add_argument("--log", type=Path, default=None, help="CSV event log; omit to generate")
    att.add_argument("--convention", default="largest_cause", choices=CONVENTIONS)
    att.add_argument("--granularity", default=None, choices=sorted(GRANULARITIES))
    att.add_argument("--json", type=Path, default=None)

    res = sub.add_parser("resolution", help="what the sample and the clock can support")
    res.add_argument("--log", type=Path, default=None)
    res.add_argument("--claim", type=float, default=0.95)
    return parser


def _load_log(path: Path | None) -> list[Shipment]:
    if path is None:
        return generate_log(2_000)[0]
    import pandas as pd

    frame = pd.read_csv(path)
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise AttributionError(f"event log is missing columns: {', '.join(missing)}")
    for column in COLUMNS[2:]:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any():
            raise AttributionError(f"column '{column}' contains values that are not numbers")
        frame[column] = numeric.astype(int)
    if len(frame) < DEFAULTS.min_shipments:
        raise AttributionError(
            f"{len(frame)} shipments is below the minimum of {DEFAULTS.min_shipments}; "
            "an attribution over fewer is a set of rates with no denominators"
        )
    return [
        Shipment(**{column: row[column] for column in COLUMNS}).validate()
        for _, row in frame.iterrows()
    ]


def _run_generate(args: argparse.Namespace) -> int:
    import pandas as pd

    log, truth = generate_log(args.shipments, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([shipment.as_dict() for shipment in log]).to_csv(args.out, index=False)
    print(f"wrote {len(log)} shipments across {len(LANES)} lanes to {args.out}")
    if args.truth:
        args.truth.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"shipment_id": [s.shipment_id for s in log], "planted_cause": truth}).to_csv(
            args.truth, index=False
        )
        print(f"wrote the planted causes to {args.truth}")
    return EXIT_OK


def _run_attribute(args: argparse.Namespace) -> int:
    log = _load_log(args.log)
    if args.granularity:
        log = [coarsen(shipment, args.granularity) for shipment in log]
    summary, rows = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS, args.convention)
    verdict = judge(summary)

    print(
        f"{summary.shipments} shipments, {summary.late} delivered late "
        f"({1 - summary.on_time_rate:.1%})"
        + (f", timestamps rounded to the {args.granularity}" if args.granularity else "")
    )
    print()
    print(render_causes(summary))
    print()
    print(f"VERDICT: {verdict.status}")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    for warning in verdict.warnings:
        print(f"  ! {warning}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "summary": summary.as_dict(),
                    "upstream_share_of_late": summary.upstream_share_of_late,
                    "multiple_cause_share": summary.multiple_cause_share,
                    "scorecard_precision": summary.scorecard_precision,
                    "verdict": {
                        "status": verdict.status,
                        "reasons": list(verdict.reasons),
                        "warnings": list(verdict.warnings),
                    },
                    "attributions": [row.as_dict() for row in rows[:50]],
                },
                indent=2,
            )
            + "\n"
        )
    return verdict.exit_code


def _run_resolution(args: argparse.Namespace) -> int:
    log = _load_log(args.log)
    summary, _ = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
    precision = rate_with_floor(
        summary.carrier_flagged_and_truly_carrier, summary.carrier_flagged, args.claim
    )
    print(
        f"Scorecard precision {precision.rate:.1%} over {precision.denominator} flagged "
        f"shipments. The smallest rate this sample can distinguish is "
        f"{precision.floor:.1%}."
    )
    print(
        f"Against a claim of {args.claim:.0%}, the sample "
        + ("can" if precision.supported else "cannot")
        + " tell the two apart."
    )
    if not precision.supported:
        print(
            f"  It would take about {precision.samples_needed()} flagged shipments to "
            "separate them."
        )
    print()
    print("What each clock granularity leaves of the attribution:")
    for granularity in sorted(GRANULARITIES, key=lambda name: GRANULARITIES[name]):
        coarse, _ = attribute_log(
            [coarsen(shipment, granularity) for shipment in log],
            lanes_by_name(),
            DEPART_FLOOR_SECONDS,
        )
        print(
            f"  {granularity:<13} {coarse.late:>5} late, "
            f"{coarse.upstream_share_of_late:>6.1%} upstream"
        )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK

    handlers = {
        "generate": _run_generate,
        "attribute": _run_attribute,
        "resolution": _run_resolution,
    }
    try:
        return handlers[args.command](args)
    except AttributionError as exc:
        print(f"cannot answer: {exc}", file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    except (ValueError, OSError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
