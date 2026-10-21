"""How much of the attribution survives the clock the transport system actually keeps?

Question the README asks: every finding here depends on knowing whether a
release landed before or after a cutoff. A system that records milestones to
the hour cannot answer that for a six minute miss, and one that records to the
day cannot answer it at all.

The failure is quiet. A coarser clock does not report an error; it reports
fewer late shipments and a different mix of causes, which reads as a better
operation. That is the most dangerous shape a measurement error can take.

Both rounding modes are run, because the choice is not neutral and a transport
system has already made it without recording which.
"""

from __future__ import annotations

import numpy as np
from _harness import REPLICATIONS, SHIPMENTS, emit

from tta.attribute import attribute_log
from tta.config import GRANULARITIES
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.resolution import coarsen

MODES = ("floor", "nearest")


def main() -> None:
    series, rows = [], []
    for granularity in sorted(GRANULARITIES, key=lambda name: GRANULARITIES[name]):
        for mode in MODES:
            late, upstream = [], []
            for replication in range(REPLICATIONS):
                log, _ = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
                summary, _ = attribute_log(
                    [coarsen(shipment, granularity, mode) for shipment in log],
                    lanes_by_name(),
                    DEPART_FLOOR_SECONDS,
                )
                late.append(summary.late)
                upstream.append(summary.upstream_share_of_late)
            series.append(
                {
                    "granularity": granularity,
                    "mode": mode,
                    "seconds": GRANULARITIES[granularity],
                    "late_mean": float(np.mean(late)),
                    "late_sd": float(np.std(late, ddof=1)),
                    "upstream_share_mean": float(np.mean(upstream)),
                    "upstream_share_sd": float(np.std(upstream, ddof=1)),
                }
            )
            rows.append(
                (
                    granularity,
                    mode,
                    f"{np.mean(late):.0f}",
                    f"{np.mean(upstream):.1%}",
                    f"{np.std(upstream, ddof=1) * 100:.2f}",
                )
            )

    def pick(granularity: str, mode: str = "floor") -> dict:
        return next(
            row for row in series if row["granularity"] == granularity and row["mode"] == mode
        )

    finest, coarsest, hourly = pick("minute"), pick("day"), pick("hour")
    emit(
        "exp04_clock_granularity",
        {
            "question": "how much of the attribution survives a coarser clock",
            "replications": REPLICATIONS,
            "series": series,
            "late_lost_to_daily_clock_share": 1.0 - coarsest["late_mean"] / finest["late_mean"],
            "upstream_share_shift_at_daily_points": (
                finest["upstream_share_mean"] - coarsest["upstream_share_mean"]
            )
            * 100,
            "upstream_share_shift_at_hourly_points": abs(
                finest["upstream_share_mean"] - hourly["upstream_share_mean"]
            )
            * 100,
            "note": (
                "an hourly clock costs almost nothing, which was not the expected "
                "result and is reported as measured. A daily clock loses most of the "
                "late shipments outright, and it does so silently: nothing errors, the "
                "operation simply looks better than it is"
            ),
        },
        rows,
        ("granularity", "rounding", "late", "upstream share", "sd pts"),
    )


if __name__ == "__main__":
    main()
