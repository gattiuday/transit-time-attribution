"""Fail the build when a document quotes a figure the code no longer produces.

Carried over from a sibling repository where the first version of this checker
failed an audit: sixteen published figures were corrupted one at a time and
fourteen passed. This is the rebuilt version, with the three causes already
closed. They are worth restating, because each one looks like a reasonable
design decision until it is tested:

1. **Fenced blocks were stripped wholesale.** The convention table, which is the
   centrepiece of the README, lives in a fence, so seven published values had no
   guard at all. Now only fences tagged as commands (```bash) are stripped,
   because an example invocation may legitimately contain an invented row count.
   A results block is prose with a monospace font and is checked like prose.

2. **An anchor matching in one document satisfied every document.** The defense
   guide quotes the same figures and was therefore almost entirely unguarded.
   Now every checked document is checked on its own.

3. **The reverse check only printed a note.** That was the real hole. A forward
   check can only confirm that a correct sentence exists somewhere; it cannot
   notice a corrupted one. Corrupting 2.86 to 9.99 leaves the anchored sentence
   absent *and* introduces a number matching no metric, and it is the second of
   those that catches a figure quoted in a table cell or a prose aside. The
   reverse check now fails the build, and the allowed list is small enough that
   it means something.

Anchors are still alternatives within a document, because the same figure reads
differently in a table and in a sentence, and requiring all of them would fail
the build for prose that is perfectly correct.

`tests/test_check_numbers.py` corrupts every published figure in turn and
asserts this script exits non zero. A checker nobody has watched fail is a
checker nobody should believe, and this one is only trusted here because it was
watched failing somewhere else first.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "docs" / "metrics.json"

#: Only command fences are stripped. A bare fence holds results and is checked.
COMMAND_FENCE = re.compile(r"```(?:bash|sh|console|python)\n.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
#: An indented code block, which markdown renders as code and which therefore
#: holds formulae rather than claims. Without this, the exponent in
#: "sigma_D^2" is read as a published figure.
INDENTED_CODE = re.compile(r"(?m)^(?: {4}|\t).*$")
HTML_ATTRIBUTE = re.compile(r'\w+="[^"]*"')
MARKDOWN_TARGET = re.compile(r"\]\([^)]*\)")
#: A clock time. "16:05" is two numbers to a digit scanner and one time to a
#: reader, and neither of its halves is a measurement. Stripped before anything
#: else runs, because otherwise every cutoff hour in the prose reads as a claim.
CLOCK_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
#: Markdown emphasis. It is formatting, not content, and a pair of asterisks
#: between an anchor's words stops the anchor matching prose that is correct.
BOLD = re.compile(r"\*\*?")
#: A number as a document writes one, thousands separators included. Without
#: the comma group, "200,000" reads as a 200 and a 000, neither of which matches
#: any metric, so a correctly quoted figure fails the reverse check.
NUMBER = re.compile(
    r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?![\w.])"
    r"|(?<![\w.,])\d+(?:\.\d+)?(?!,\d{3})(?![\w.])"
)
#: shields.io badge values. A badge is a published claim sitting in the first
#: screen, and stripping markdown targets hid it from both checks. The test
#: suite found that: corrupting the test count only changed the badge, and the
#: build stayed green.
BADGE = re.compile(r"img\.shields\.io/badge/(?P<label>[^-\s]+)-(?P<value>[^-\s]+)-")
BADGE_RANGE = re.compile(r"img\.shields\.io/badge/(?P<label>[a-z]+)-(?P<value>[\d.%A-F]+)-")

#: Numbers that appear for reasons unrelated to a measurement. Deliberately
#: short: every entry here is a figure the reverse check can no longer catch,
#: so each one is a hole that has to earn its place. Values that look like
#: results (the fixture's shape, the supported Python versions) are declared as
#: metrics in collect_metrics.py instead of being whitelisted here.
ALLOWED_BARE_NUMBERS = {
    # small ordinals and counts used structurally in prose
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    # ADR file numbers as they appear in link text and cross references
    "001",
    "002",
    "003",
    "004",
    "005",
    "006",
    "007",
}


#: In a Python source file only the prose carries claims. Code is full of
#: indices, version pins and array sizes that are not measurements, so a source
#: file is reduced to its docstrings before anything else runs.
DOCSTRING = re.compile(r'"""(.*?)"""', re.DOTALL)


def docstrings_only(text: str) -> str:
    """Everything between triple quotes, and nothing else."""
    return "\n".join(DOCSTRING.findall(text))


def strip_non_prose(text: str) -> str:
    """Remove the parts of a document that may legitimately contain invented numbers."""
    text = COMMAND_FENCE.sub(" ", text)
    text = CLOCK_TIME.sub(" ", text)
    text = BOLD.sub("", text)
    text = INDENTED_CODE.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = MARKDOWN_TARGET.sub(" ", text)
    return HTML_ATTRIBUTE.sub(" ", text)


def flatten(text: str) -> str:
    """Collapse every run of whitespace, newlines included.

    An anchor phrase that spans a line break in wrapped markdown matched nothing
    while the prose it guarded was correct. Collapsing only horizontal space was
    not enough: a re-audit found "about 160 SKUs" failing against a document
    that said exactly that, with a newline between the number and the noun.
    """
    return re.sub(r"\s+", " ", text)


def normalise(text: str) -> str:
    """Collapse whitespace so an anchor still matches across a wrapped line.

    An anchor phrase that spans a newline in wrapped markdown matches nothing
    while the prose it guards is correct, so anchors are matched against a
    single spaced version of the document.
    """
    return re.sub(r"[^\S\n]+", " ", text)


def load_documents(payload: dict) -> dict[str, str] | None:
    documents = {}
    for name in payload["checked_documents"]:
        path = ROOT / name
        if not path.exists():
            print(f"FAIL  checked document is missing: {name}", file=sys.stderr)
            return None
        body = path.read_text()
        if name.endswith(".py"):
            body = docstrings_only(body)
        documents[name] = normalise(strip_non_prose(body))
    return documents


def forward_check(
    payload: dict, documents: dict[str, str]
) -> tuple[list[str], list[str], set[tuple[str, int, str]]]:
    """Every anchored metric must appear, inside an anchor phrase, where it is claimed.

    A metric is required in a document only if that document mentions its value
    at all. That keeps the README's exclusive figures from being demanded of the
    defense guide, while still checking any figure the defense guide does quote.
    """
    formatted, anchors = payload["formatted"], payload["anchors"]
    verified, failures = [], []
    #: Every (document, line, value) where an anchor phrase actually matched.
    #: The reverse check uses it to require that a published number appear only
    #: where some anchor put it. An audit showed why the previous version was
    #: not enough: it suppressed a value document wide once any anchor matched
    #: it anywhere, so corrupting one figure into another published figure's
    #: value passed, including the first sentence of the README.
    #: A value appearing only inside a generated block needs no anchor: block
    #: equality guards it, more tightly than any phrase could. The reverse check
    #: already skips those regions and the forward check must skip them too, or
    #: a correct document fails because a measured value happens to appear in a
    #: table cell.
    sites: Counter[tuple[str, int, str]] = Counter()
    for metric in sorted(anchors):
        phrases = anchors[metric]
        value = formatted.get(metric)
        if value is None:
            failures.append(f"{metric}: anchored but never measured")
            continue
        if value in ALLOWED_BARE_NUMBERS and phrases:
            # Nothing can verify this. The reverse check allows the value
            # everywhere, so an anchor for it proves only that the phrase is
            # present, and the figure could be replaced by any other allowed
            # ordinal without a complaint. Counting it among the verified
            # figures overstates what is checked, so it is an error to declare
            # one: either the figure belongs in words, or the ordinal set is
            # wrong.
            failures.append(
                f"{metric}: its value {value} is in the allowed ordinal set, so no anchor "
                "can verify it; write the figure in words or narrow the ordinal set"
            )
            continue
        if not phrases:
            # A deliberate opt out, for a value published only on a badge, where
            # `badge_check` guards it and no prose anchor applies. Any other
            # empty list is a metric nothing re-checks, which is the gap this
            # script exists to close, so it is reported either way and the
            # metric's own entry says which it is.
            if metric in payload.get("badge_only", []):
                continue
            failures.append(f"{metric}: has no anchor phrase, so nothing re-checks the prose")
            continue
        candidates = [flatten(phrase.format(value)) for phrase in phrases]
        quoted = False
        for name, raw in documents.items():
            # The same body the reverse check reads. Stripping a generated block
            # collapses it to one space and shifts every line number after it,
            # so a site recorded against the unstripped body points at the wrong
            # line in the stripped one and the two halves of this script
            # silently stop agreeing about where anything is.
            body = strip_generated_blocks(payload, name, raw)
            lines = body.split("\n")
            found = False
            for index, line in enumerate(lines):
                # An anchor may straddle a line break in wrapped markdown, so
                # each line is tested together with the next.
                following = lines[index + 1] if index + 1 < len(lines) else ""
                # The seam is normalised to exactly one space so that the
                # window is the concatenation of two known pieces and an offset
                # inside it can be told which line it came from. Flattening the
                # join as one string, which is what this did before, leaves the
                # boundary unrecoverable whenever a wrapped line is indented.
                head = flatten(line.rstrip())
                window = head + " " + flatten(following.strip())
                # Where in the window each matched phrase puts the value. A set
                # of offsets rather than a count of matches, because the phrase
                # list is allowed to contain overlapping phrases and often does:
                # "{}% of the time" and "right {}% of the time" both match the
                # same text, and summing their counts credited the line with two
                # anchored occurrences of a value quoted once. That is how the
                # README headline stayed green when its upstream share was
                # replaced by the precision quoted later on the same line.
                offsets = set()
                for candidate in candidates:
                    inside = candidate.find(value)
                    start = window.find(candidate)
                    while start != -1:
                        offsets.add(start + inside)
                        start = window.find(candidate, start + 1)
                if not offsets:
                    continue
                found = True
                # How many occurrences of this value the matched phrases
                # account for, and on which of the two lines they sit.
                #
                # This used to record the value against both lines and ask only
                # whether the pair was present, which is a hole wherever two
                # anchored figures share a line: either could be replaced by
                # the other and the pair was still present. An audit changed
                # the README's first sentence from one measured value to a
                # different measured value and the build stayed green, which is
                # the failure the docstring below already claimed to have
                # fixed. Counting occurrences per line closes it, because the
                # corruption leaves one value appearing more often on that line
                # than the anchors there account for.
                boundary = len(head) + 1
                on_this_line = sum(1 for offset in offsets if offset < boundary)
                on_next_line = len(offsets) - on_this_line
                for offset, occurrences in ((1, on_this_line), (2, on_next_line)):
                    if occurrences:
                        key = (name, index + offset, value)
                        sites[key] = max(sites[key], occurrences)
            if found:
                quoted = True
                verified.append(f"OK    {metric} = {value}  ({name})")
            elif value in NUMBER.findall(body):
                failures.append(
                    f"{metric} = {value} appears in {name} but not inside any anchor: "
                    + " | ".join(repr(c) for c in candidates)
                )
        if not quoted:
            # Deleting a figure from the prose passed every check. The forward
            # check requires a metric only in a document that mentions its
            # value, so a figure removed everywhere was required of none, and an
            # audit deleted a published standard deviation from both documents
            # with the build staying green. A receipts system whose stated
            # uncertainty can be dropped silently is not reporting uncertainty.
            failures.append(
                f"{metric}: measured and anchored but quoted in no checked document, so "
                "nothing published reports it"
            )
    return verified, failures, sites


def strip_generated_blocks(payload: dict, name: str, body: str) -> str:
    """Remove block guarded regions before the reverse check reads a document.

    A generated block is checked by equality against what the code produced, so
    every number inside it is already guarded, and more tightly than any anchor
    phrase could manage. Asking the reverse check to also account for each cell
    would mean publishing every cell as a metric purely to widen the allowed
    set, which is the laundering this script exists to prevent.
    """
    for block_name in payload.get("generated_blocks", {}).get(name, []):
        source = ROOT / "docs" / "generated" / block_name
        if source.exists():
            body = body.replace(normalise(source.read_text().rstrip("\n")), " ")
    return body


def reverse_check(
    payload: dict, documents: dict[str, str], sites: Counter[tuple[str, int, str]]
) -> list[str]:
    """Every number must be an allowed ordinal, or sit where an anchor put it.

    This is the half that catches a corrupted figure, and it is only as strong
    as what it compares against. The first version asked whether a number was
    anywhere in the set of published values, which let any figure be swapped for
    any other: an audit changed the README's first sentence from one measured
    value to a different measured value and the build stayed green.

    So membership is not enough, and nor is presence on the line. A number passes
    only if an anchor phrase for that exact value matched on that line, and only
    as many times as the anchors there account for. Presence alone was the
    second version of this check and it was also broken: wherever two anchored
    figures share a line, each was recorded against that line, so either could
    be replaced by the other and both were still present. Counting is what
    separates a figure appearing where an anchor put it from a figure appearing
    where a different anchor put a different figure.
    """
    failures = []
    for name, raw in documents.items():
        body = strip_generated_blocks(payload, name, raw)
        for line_number, line in enumerate(body.split("\n"), start=1):
            seen = Counter(
                found for found in NUMBER.findall(line) if found not in ALLOWED_BARE_NUMBERS
            )
            for found, count in sorted(seen.items()):
                allowed = sites.get((name, line_number, found), 0)
                if count <= allowed:
                    continue
                if allowed:
                    failures.append(
                        f"{name}:{line_number}: {found} appears {count} times but anchor "
                        f"phrases account for {allowed} of them"
                    )
                else:
                    failures.append(
                        f"{name}:{line_number}: {found} is not an allowed ordinal and no "
                        "anchor phrase claims it here"
                    )
    return failures


#: Which badge label must equal which metric.
BADGE_METRICS = {"tests": "tests_total", "coverage": "coverage_line_pct"}

#: Badges whose value is a list rather than a single figure. The python badge
#: advertises the supported versions and was checked against neither
#: pyproject's floor nor the CI matrix; the argument for checking the other two
#: applies to it unchanged.
BADGE_RANGES = {"python": "python_min_version"}


def badge_check(payload: dict) -> list[str]:
    """Badge values are published claims and must match the measured metric."""
    formatted = payload["formatted"]
    failures = []
    for name in payload["checked_documents"]:
        for match in BADGE.finditer((ROOT / name).read_text()):
            label = match.group("label")
            metric = BADGE_METRICS.get(label)
            if metric is None:
                continue
            expected = formatted[metric]
            actual = match.group("value").replace("%25", "").replace("%20", " ")
            if actual != expected:
                failures.append(
                    f"{name}: the {label} badge reads {actual} but {metric} measures {expected}"
                )
        for match in BADGE_RANGE.finditer((ROOT / name).read_text()):
            metric = BADGE_RANGES.get(match.group("label"))
            if metric is None:
                continue
            listed = match.group("value").replace("%20", " ").replace("%7C", "|")
            floor = formatted[metric]
            if not listed.strip().startswith(floor):
                failures.append(
                    f"{name}: the {match.group('label')} badge lists '{listed}' but the "
                    f"project's own floor is {floor}"
                )
    return failures


def block_check(payload: dict) -> list[str]:
    """Generated blocks must appear in their document verbatim.

    Twelve cells of a fixed width table cannot realistically be guarded by
    anchor phrases. Block equality guards all of them at once, and it is a
    stronger guarantee than any phrase: the document either contains exactly
    what the code produced, or it does not.
    """
    failures = []
    for name, blocks in payload.get("generated_blocks", {}).items():
        document = (ROOT / name).read_text()
        for block_name in blocks:
            source = ROOT / "docs" / "generated" / block_name
            if not source.exists():
                failures.append(f"{name}: generated block {block_name} has not been written")
                continue
            if source.read_text().rstrip("\n") not in document:
                failures.append(
                    f"{name}: does not contain docs/generated/{block_name} verbatim; "
                    "the document has drifted from what the code produced"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=None, help="also write a markdown summary")
    parser.add_argument(
        "--metrics", type=Path, default=METRICS_PATH, help="metrics file to check against"
    )
    args = parser.parse_args()

    if not args.metrics.exists():
        print(f"{args.metrics} is missing; run tools/collect_metrics.py first", file=sys.stderr)
        return 2
    payload = json.loads(args.metrics.read_text())

    documents = load_documents(payload)
    if documents is None:
        return 1

    verified, stale, sites = forward_check(payload, documents)
    unverified = reverse_check(payload, documents, sites)
    # These were summed into one counter reported as "generated blocks drifted",
    # so a badge mismatch printed a count of drifted blocks when no block had
    # drifted. Two different checks deserve two counters.
    drifted = block_check(payload)
    badges = badge_check(payload)

    for line in verified:
        print(line)
    for failure in stale:
        print(f"FAIL  {failure}", file=sys.stderr)
    for failure in unverified:
        print(f"FAIL  {failure}", file=sys.stderr)
    for failure in drifted + badges:
        print(f"FAIL  {failure}", file=sys.stderr)

    total = len(stale) + len(unverified) + len(drifted) + len(badges)
    print(
        f"\n{len(verified)} anchored figures verified across "
        f"{len(documents)} documents, {len(stale)} stale, "
        f"{len(unverified)} numbers matching no metric, "
        f"{len(drifted)} generated blocks drifted, "
        f"{len(badges)} badges disagreeing with the run"
    )

    if args.summary:
        args.summary.write_text(
            "## Receipts\n\n"
            f"- {len(verified)} anchored figures verified across {len(documents)} documents\n"
            f"- {len(stale)} figures quoted outside their anchor phrase\n"
            f"- {len(unverified)} numbers in prose matching no measured metric\n\n"
            + f"- {len(drifted)} generated blocks that have drifted\n"
            + f"- {len(badges)} badges disagreeing with the run\n\n"
            + (
                "\n".join(f"- FAIL {f}" for f in stale + unverified + drifted + badges)
                if total
                else ""
            )
            + "\n"
        )
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
