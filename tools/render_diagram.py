"""Render the architecture diagram to a committed SVG.

GitHub's Mermaid renderer fails intermittently with an error that comes from
inside their lazily loaded bundle, so a mermaid fence in a README is not a
reliable way to show a diagram. This script writes the SVG directly, with
explicit intrinsic dimensions and a painted background, so it renders
identically on GitHub, in an editor preview, in a PDF export, and offline.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "img" / "architecture.svg"

WIDTH, HEIGHT = 980, 580

BOX = 'fill="#ffffff" stroke="#4a5568" stroke-width="1.6" rx="6"'
ACCENT = 'fill="#fff8e6" stroke="#b7791f" stroke-width="1.8" rx="6"'
MUTED = 'fill="#f7fafc" stroke="#a0aec0" stroke-width="1.4" rx="6"'
LABEL = 'font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#1a202c"'
SMALL = 'font-family="Helvetica,Arial,sans-serif" font-size="11" fill="#4a5568"'
TITLE = 'font-family="Helvetica,Arial,sans-serif" font-size="12" font-weight="bold" fill="#2d3748"'


def box(x, y, w, h, style, lines, line_style=LABEL):
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {style}/>']
    start = y + h / 2 - (len(lines) - 1) * 8
    for index, line in enumerate(lines):
        style_for_line = line_style if index == 0 else SMALL
        parts.append(
            f'<text x="{x + w / 2}" y="{start + index * 16 + 4}" text-anchor="middle" '
            f"{style_for_line}>{line}</text>"
        )
    return "\n".join(parts)


def arrow(x1, y1, x2, y2, label=""):
    parts = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#4a5568" '
        'stroke-width="1.5" marker-end="url(#head)"/>'
    ]
    if label:
        parts.append(
            f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 6}" text-anchor="middle" '
            f"{SMALL}>{label}</text>"
        )
    return "\n".join(parts)


def build() -> str:
    body = [
        f'<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="{WIDTH / 2}" y="30" text-anchor="middle" '
        'font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="bold" '
        'fill="#1a202c">transit-time-attribution: where the scorecard starts counting</text>',
        box(30, 70, 150, 58, MUTED, ["order created"]),
        arrow(180, 99, 236, 99),
        box(236, 70, 150, 58, MUTED, ["released"]),
        arrow(386, 99, 442, 99),
        box(442, 70, 150, 58, MUTED, ["ship confirm"]),
        arrow(592, 99, 648, 99),
        box(648, 70, 150, 58, MUTED, ["delivered"]),
        f'<text x="208" y="152" text-anchor="middle" {TITLE}>order to release</text>',
        f'<text x="208" y="168" text-anchor="middle" {SMALL}>warehouse picking</text>',
        f'<text x="414" y="152" text-anchor="middle" {TITLE}>release to depart</text>',
        f'<text x="414" y="168" text-anchor="middle" {SMALL}>waiting for a departure</text>',
        f'<text x="620" y="152" text-anchor="middle" {TITLE}>transit</text>',
        f'<text x="620" y="168" text-anchor="middle" {SMALL}>the committed window</text>',
        '<rect x="442" y="56" width="356" height="130" fill="none" stroke="#b7791f" '
        'stroke-width="2" stroke-dasharray="6 4" rx="6"/>',
        f'<text x="620" y="205" text-anchor="middle" {TITLE}>the carrier scorecard measures only this</text>',
        box(
            30,
            240,
            356,
            92,
            ACCENT,
            [
                "outside the scorecard entirely",
                "a late release, or a release that missed",
                "the cutoff and waited for tomorrow.",
                "Minutes become a day.   ADR-003",
            ],
        ),
        box(
            442,
            240,
            356,
            92,
            BOX,
            [
                "inside the scorecard",
                "the carrier exceeded its committed",
                "transit. Routinely beaten on a shipment",
                "the warehouse made late.",
            ],
        ),
        arrow(208, 186, 208, 240),
        arrow(620, 220, 620, 240),
        box(
            30,
            372,
            356,
            78,
            ACCENT,
            [
                "planted ground truth",
                "the generator writes down which stage",
                "caused each late delivery, so the",
                "attribution is graded   exp01",
            ],
        ),
        box(
            442,
            372,
            356,
            78,
            BOX,
            [
                "resolution limits",
                "a daily clock loses most of the lateness,",
                "and a rate over few flags resolves nothing",
                "exp04, exp05",
            ],
        ),
        box(
            180,
            490,
            620,
            62,
            MUTED,
            [
                "verdict: is the scorecard measuring the lateness that happened",
                "0 yes   1 it misses a material share   2 cannot answer   3 usage",
            ],
        ),
        arrow(208, 450, 360, 490),
        arrow(620, 450, 620, 490),
    ]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">\n'
        '<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#4a5568"/></marker></defs>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(build())
    print(f"wrote {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
