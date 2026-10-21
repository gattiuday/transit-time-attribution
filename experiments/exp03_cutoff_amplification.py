"""What does a missed cutoff cost, and why does that make carriers incomparable?

Question the README asks: a shipment released five minutes after a cutoff does
not leave five minutes late. It waits for the next departure. On a lane with one
departure a day that is twenty four hours; on a lane with three it is a few
hours. The same upstream error therefore produces wildly different customer
lateness depending on a timetable the carrier does not control.

The consequence is the finding. A scorecard that compares carriers across lanes
of different departure frequency is comparing timetables, and the carrier on the
lane with the most forgiving schedule will look best whatever it does.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

import numpy as np
from _harness import REPLICATIONS, SHIPMENTS, emit

from tta.attribute import attribute_log
from tta.config import LANES, departure_slots
from tta.generator import DEPART_FLOOR_SECONDS, generate_log, lanes_by_name
from tta.stages import SECONDS_PER_DAY


def main() -> None:
    lanes = {lane.name: lane for lane in LANES}
    totals: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for replication in range(REPLICATIONS):
        log, _ = generate_log(SHIPMENTS, seed=20261021 + 97 * replication)
        _, rows = attribute_log(log, lanes_by_name(), DEPART_FLOOR_SECONDS)
        per_lane: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            bucket = per_lane[row.lane]
            bucket["shipments"] += 1
            bucket["late"] += int(row.is_late)
            bucket["carrier_caused"] += int(row.is_late and row.cause == "transit")
            if row.is_late:
                bucket["lateness_seconds"] += row.delivery_lateness
        for name, bucket in per_lane.items():
            totals[name]["late_rate"].append(bucket["late"] / bucket["shipments"])
            totals[name]["carrier_rate"].append(bucket["carrier_caused"] / bucket["shipments"])
            totals[name]["carrier_share_of_late"].append(bucket["carrier_caused"] / bucket["late"])
            totals[name]["mean_lateness_days"].append(
                bucket["lateness_seconds"] / bucket["late"] / SECONDS_PER_DAY
            )

    rows_out, per_lane_out = [], {}
    for name in (lane.name for lane in LANES):
        lane = lanes[name]
        slots = departure_slots(lane)
        worst_wait = (
            SECONDS_PER_DAY
            if len(slots) == 1
            else max(later - earlier for earlier, later in pairwise(slots))
        )
        measures = {
            key: {
                "mean": float(np.mean(values)),
                "sd": float(np.std(values, ddof=1)),
            }
            for key, values in totals[name].items()
        }
        per_lane_out[name] = {
            "departures_per_day": lane.departures_per_day,
            "cutoff_hour": lane.cutoff_hour,
            "worst_missed_cutoff_cost_seconds": int(worst_wait),
            "worst_missed_cutoff_cost_hours": worst_wait / 3600,
            **measures,
        }
        rows_out.append(
            (
                name,
                lane.departures_per_day,
                f"{worst_wait / 3600:.0f}",
                f"{measures['late_rate']['mean']:.1%}",
                f"{measures['carrier_rate']['mean']:.1%}",
                f"{measures['carrier_share_of_late']['mean']:.1%}",
            )
        )

    single = [v for v in per_lane_out.values() if v["departures_per_day"] == 1]
    multi = [v for v in per_lane_out.values() if v["departures_per_day"] > 1]
    worst_carrier = max(per_lane_out.items(), key=lambda kv: kv[1]["carrier_rate"]["mean"])
    best_otif = min(per_lane_out.items(), key=lambda kv: kv[1]["late_rate"]["mean"])

    emit(
        "exp03_cutoff_amplification",
        {
            "question": "what does a missed cutoff cost, and does it make lanes comparable",
            "replications": REPLICATIONS,
            "per_lane": per_lane_out,
            "single_departure_late_rate": float(np.mean([v["late_rate"]["mean"] for v in single])),
            "multi_departure_late_rate": float(np.mean([v["late_rate"]["mean"] for v in multi])),
            "single_departure_carrier_share": float(
                np.mean([v["carrier_share_of_late"]["mean"] for v in single])
            ),
            "multi_departure_carrier_share": float(
                np.mean([v["carrier_share_of_late"]["mean"] for v in multi])
            ),
            "worst_carrier_lane": worst_carrier[0],
            "best_otif_lane": best_otif[0],
            "worst_carrier_is_best_otif": worst_carrier[0] == best_otif[0],
            "note": (
                "every lane is generated with the same mix of planted causes, so the "
                "carriers are equally good by construction. The lane with the most "
                "departures still shows the best delivered service and the largest "
                "carrier share of its own lateness, because a forgiving timetable "
                "absorbs upstream error and leaves only the carrier's own"
            ),
        },
        rows_out,
        (
            "lane",
            "dep/day",
            "missed cutoff costs (h)",
            "late",
            "carrier caused",
            "carrier share of late",
        ),
    )


if __name__ == "__main__":
    main()
