"""Capture the real console output as a framed SVG, and a replay manifest.

Everything here is produced by running the tool, never by typesetting a
screenshot by hand. The manifest records each command with its exit code so a
reviewer can rerun exactly what was captured and compare.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "docs" / "img"
MANIFEST = ROOT / "docs" / "evidence-manifest.json"

COMMANDS = (
    (
        "attribute",
        [sys.executable, "-m", "tta.cli", "attribute", "--log", "data/fixtures/event-log.csv"],
    ),
    (
        "resolution",
        [sys.executable, "-m", "tta.cli", "resolution", "--log", "data/fixtures/event-log.csv"],
    ),
)

CHAR_W, LINE_H, PAD, TITLE_H = 8.0, 18, 18, 34
BG, FG, ACCENT, DIM = "#1b1f27", "#e6edf3", "#ffd479", "#7d8590"


def run(command: list[str]) -> tuple[str, int, float]:
    env = {
        "PYTHONPATH": str(ROOT / "src"),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "COLUMNS": "100",
    }
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    return result.stdout + result.stderr, result.returncode, time.monotonic() - started


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def to_svg(title: str, body: str, exit_code: int) -> str:
    lines = body.rstrip("\n").split("\n")
    width = int(max(len(title) + 20, max(len(line) for line in lines)) * CHAR_W) + 2 * PAD
    height = TITLE_H + len(lines) * LINE_H + 2 * PAD
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{BG}" rx="8"/>',
        f'<text x="{PAD}" y="{PAD + 14}" font-family="monospace" font-size="13" '
        f'fill="{ACCENT}">$ {escape(title)}</text>',
        f'<text x="{width - PAD}" y="{PAD + 14}" text-anchor="end" font-family="monospace" '
        f'font-size="12" fill="{DIM}">exit {exit_code}</text>',
    ]
    for index, line in enumerate(lines):
        colour = ACCENT if line.startswith(("VERDICT", "  !")) else FG
        parts.append(
            f'<text x="{PAD}" y="{PAD + TITLE_H + index * LINE_H + 12}" '
            f'font-family="monospace" font-size="12.5" fill="{colour}" '
            f'xml:space="preserve">{escape(line)}</text>'
        )
    parts.append("</svg>\n")
    return "\n".join(parts)


def main() -> int:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, command in COMMANDS:
        output, code, _elapsed = run(command)
        printable = " ".join(["python", "-m", *command[2:]])
        target = IMG_DIR / f"console-{name}.svg"
        target.write_text(to_svg(printable, output, code))
        entries.append(
            {
                "name": name,
                "command": printable,
                "exit_code": code,
                "output_lines": len(output.rstrip().split("\n")),
                "svg": str(target.relative_to(ROOT)),
            }
        )
        print(f"captured {target.relative_to(ROOT)} (exit {code}, {len(output)} chars)")

    MANIFEST.write_text(
        json.dumps(
            {
                "captures": entries,
                "note": (
                    "each SVG is the verbatim stdout of the command named in it, "
                    "rendered by this script. No duration is recorded: a wall clock "
                    "reading is a fact about the machine, and a committed file whose "
                    "contents change on every run makes a drift gate meaningless."
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
