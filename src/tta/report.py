"""Verdict and console rendering, kept separate from the arithmetic.

The modules above say what the numbers are. This one says what they mean under
a stated policy, and the policy lives in `config` where it can be argued with.

The verdict is about the scorecard rather than about the carrier. This package
has no opinion on whether a carrier is good; it has a measurement of whether
the scorecard measuring that carrier can see the thing it is being blamed for.
"""

from __future__ import annotations

from dataclasses import dataclass

from tta.attribute import LogAttribution
from tta.config import DEFAULTS, Thresholds
from tta.stages import CARRIER_STAGE

SCORECARD_SOUND = "scorecard_sees_the_lateness"
SCORECARD_BLIND = "scorecard_misses_most_lateness"


@dataclass(frozen=True)
class Verdict:
    status: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 0 if self.status == SCORECARD_SOUND else 1


def judge(summary: LogAttribution, thresholds: Thresholds = DEFAULTS) -> Verdict:
    """Decide whether a carrier scorecard is measuring the lateness that happened."""
    reasons: list[str] = []
    warnings: list[str] = []

    upstream = summary.upstream_share_of_late
    if upstream > thresholds.material_share:
        status = SCORECARD_BLIND
        reasons.append(
            f"{upstream:.1%} of late deliveries were caused by a stage that ends before "
            "ship confirm, which is where a carrier scorecard starts counting"
        )
        reasons.append(
            f"{summary.late_but_carrier_looks_fine} of {summary.late} late deliveries "
            "arrived with the carrier inside its committed window, so the scorecard "
            "records them as a carrier success"
        )
    else:
        status = SCORECARD_SOUND
        reasons.append(
            f"only {upstream:.1%} of late deliveries originated upstream of ship confirm, "
            f"below the limit of {thresholds.material_share:.0%}, so the scorecard is "
            "measuring most of what went wrong"
        )

    if summary.carrier_flagged:
        precision = summary.scorecard_precision
        reasons.append(
            f"of the {summary.carrier_flagged} shipments the scorecard does flag, "
            f"{precision:.0%} were genuinely the carrier"
        )
        if precision > 0.8:
            warnings.append(
                "the scorecard is accurate about what it flags and blind to most of the "
                "problem, which is the harder failure to notice: a metric that is rarely "
                "wrong reads as trustworthy"
            )

    if summary.shipments < thresholds.min_shipments:
        warnings.append(
            f"{summary.shipments} shipments is below the minimum of "
            f"{thresholds.min_shipments}; these shares are quoted to a precision the "
            "sample does not support"
        )

    if summary.late_with_multiple_causes:
        warnings.append(
            f"{summary.multiple_cause_share:.0%} of late deliveries had more than one "
            "stage over plan, so which single stage is named depends on the convention "
            f"and not on the data; this run used '{summary.convention}'"
        )

    return Verdict(status, tuple(reasons), tuple(warnings))


def render_causes(summary: LogAttribution) -> str:
    """A table of causes, with the scorecard's window marked.

    The marking is the point. A reader who sees three causes and one of them
    labelled as the only one inside the scorecard has understood the finding
    before reading a number.
    """
    header = f"{'cause':<22} {'late deliveries':>16} {'share of late':>14} {'scorecard':>11}"
    lines = [header, "-" * len(header)]
    for cause, count in sorted(summary.causes.items(), key=lambda item: -item[1]):
        inside = "inside" if cause == CARRIER_STAGE else "outside"
        lines.append(f"{cause:<22} {count:>16} {count / summary.late:>13.1%} {inside:>11}")
    lines += [
        "-" * len(header),
        f"{'total late':<22} {summary.late:>16} {1.0:>13.1%}",
        f"{'of which upstream':<22} {'':>16} {summary.upstream_share_of_late:>13.1%}",
    ]
    return "\n".join(lines)
