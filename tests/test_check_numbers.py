"""The number checker's own tests, because an unfallible checker is an untested one.

A sibling repository's first version of `tools/check_numbers.py` was broken by
an audit in under a minute: sixteen published figures were corrupted one at a
time and fourteen passed. The causes were that fenced results blocks were
stripped before checking, that an anchor matching in one document satisfied
every document, and that the reverse check only printed a note instead of
failing. The checker here is the rebuilt version, and these tests travel with
it, because a checker is only worth what its own test suite demonstrates.

These tests corrupt each published figure in turn and assert the checker goes
red. They are the reason the README is allowed to claim that a stale number
fails the build.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_numbers.py"
METRICS = ROOT / "docs" / "metrics.json"

sys.path.insert(0, str(ROOT / "tools"))
import check_numbers  # noqa: E402

ALLOWED_ORDINALS = check_numbers.ALLOWED_BARE_NUMBERS

pytestmark = pytest.mark.skipif(
    not METRICS.exists(),
    reason="docs/metrics.json has not been collected yet; run make receipts",
)


def _payload() -> dict:
    return json.loads(METRICS.read_text())


def _sandbox(tmp_path: Path) -> Path:
    """A copy of the repository's checked surface, so a corruption is never written back."""
    root = tmp_path / "repo"
    (root / "docs" / "generated").mkdir(parents=True)
    (root / "tools").mkdir()
    shutil.copy(CHECKER, root / "tools" / "check_numbers.py")
    shutil.copy(METRICS, root / "docs" / "metrics.json")
    for name in _payload()["checked_documents"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, target)
    for block in (ROOT / "docs" / "generated").iterdir():
        shutil.copy(block, root / "docs" / "generated" / block.name)
    return root


def _run(root: Path) -> int:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "check_numbers.py")],
        cwd=root,
        capture_output=True,
        text=True,
    ).returncode


def _corrupt(root: Path, value: str, replacement: str) -> bool:
    """Corrupt an occurrence the prose checks can see.

    Which occurrence matters. An earlier version replaced the first match
    anywhere, which for the test count landed inside a badge URL that the
    checker stripped before looking, so the build stayed green and the test
    recorded a pass that meant nothing. A later version tried to locate a
    visible occurrence by arithmetic on stripped offsets and got it wrong for
    three metrics. This one is slower and cannot be wrong: it tries each
    occurrence in turn and keeps the first whose replacement actually survives
    stripping, or is caught by the badge or block checks instead.
    """
    for name in _payload()["checked_documents"]:
        path = root / name
        original = path.read_text()
        # Standalone occurrences only. Searching for the substring found the
        # "12" inside "120" and the "20" inside "120", corrupting a neighbouring
        # figure into something the checker had no reason to reject.
        for match in re.finditer(rf"(?<![\w.]){re.escape(value)}(?![\w.])", original):
            index = match.start()
            candidate = original[:index] + replacement + original[index + len(value) :]
            # Prose only. Treating any shields.io span as visible was wrong:
            # it let a corruption land inside the python badge, which the badge
            # check validates by prefix and therefore accepted, so the test
            # passed without the checker having rejected anything. The badges
            # have their own dedicated tests below.
            visible = check_numbers.strip_non_prose(candidate)
            if replacement in visible:
                path.write_text(candidate)
                return True
    return False


def _nudge(value: str) -> str:
    """A different number of the same shape that collides with nothing.

    The first version of this helper added seven, and several of those sums
    landed on another metric's value or on an allowed ordinal, so the checker
    was right to stay green and the test was wrong to expect red. The
    replacement is now searched for rather than computed, which is slower and
    says what it means.
    """
    taken = set(_payload()["formatted"].values()) | ALLOWED_ORDINALS
    for candidate in range(811, 9999):
        text = f"{candidate}.{value.partition('.')[2]}" if "." in value else str(candidate)
        if text not in taken:
            return text
    raise AssertionError("no non colliding replacement exists")


def test_the_checker_passes_on_the_repository_as_committed(tmp_path):
    assert _run(_sandbox(tmp_path)) == 0


#: Every metric the checker claims responsibility for: anchored, in a generated
#: block, or on a badge. Parametrised over the whole set rather than a hand
#: picked few, because the figures that slipped through the first version of
#: the checker were exactly the ones nobody thought to test.
PUBLISHED = sorted(_payload()["formatted"]) if METRICS.exists() else []


@pytest.mark.parametrize("metric", PUBLISHED)
def test_corrupting_a_published_figure_fails_the_build(tmp_path, metric):
    """Every published value, corrupted in place, must turn the checker red."""
    root = _sandbox(tmp_path)
    value = _payload()["formatted"][metric]
    if not _corrupt(root, value, _nudge(value)):
        pytest.skip(f"{metric} = {value} is not quoted in any checked document")
    assert _run(root) != 0, f"corrupting {metric} = {value} did not fail the build"


def test_deleting_a_checked_document_fails_the_build(tmp_path):
    root = _sandbox(tmp_path)
    (root / "README.md").unlink()
    assert _run(root) != 0


def test_a_drifted_generated_block_fails_the_build(tmp_path):
    """The convention table is guarded by block equality rather than by phrases."""
    root = _sandbox(tmp_path)
    block = root / "docs" / "generated" / "cause-table.txt"
    block.write_text(block.read_text().replace("cause", "stage", 1))
    assert _run(root) != 0


BLOCKS = (
    "cause-table.txt",
    "lane-table.md",
    "clock-table.md",
    "convention-table.md",
)


@pytest.mark.parametrize("block_name", BLOCKS)
def test_corrupting_a_cell_of_a_generated_table_fails_the_build(tmp_path, block_name):
    """Every generated table, corrupted in the README.

    A re-audit of the sibling repository observed that its block drift test only
    ever changed a word in a header, so nothing demonstrated that a corrupted
    *number* inside a block was caught. These cases do, one per block, and they
    matter more here because four of this README's tables are generated and
    their cells are deliberately excluded from the reverse check.
    """
    root = _sandbox(tmp_path)
    readme = root / "README.md"
    block = (root / "docs" / "generated" / block_name).read_text()
    digits = [line for line in block.strip().split("\n") if re.search(r"\d", line)]
    line = digits[-1]
    body = readme.read_text()
    assert line in body, f"the README no longer contains {block_name}"
    # Increment the first digit, whatever it is. An earlier version swapped a
    # literal "9" for a "4", which silently did nothing on a block whose last
    # row happened to contain no nine.
    corrupted = re.sub(r"\d", lambda m: str((int(m.group()) + 1) % 10), line, count=1)
    assert corrupted != line
    readme.write_text(body.replace(line, corrupted, 1))
    assert _run(root) != 0


@pytest.mark.parametrize("block_name", BLOCKS)
def test_reordering_a_generated_table_fails_the_build(tmp_path, block_name):
    """Swapping two rows keeps every number and breaks the block.

    This is the case no per number check can reach: every digit is still a
    measured value, in the right document, and the table is wrong.
    """
    root = _sandbox(tmp_path)
    readme = root / "README.md"
    block = (root / "docs" / "generated" / block_name).read_text().strip()
    rows = block.split("\n")
    swapped = "\n".join([*rows[:2], rows[-1], *rows[2:-1]])
    body = readme.read_text()
    assert block in body
    readme.write_text(body.replace(block, swapped, 1))
    assert _run(root) != 0


def test_a_badge_listing_an_unsupported_python_floor_fails_the_build(tmp_path):
    """The python badge is a published claim and was unchecked until a re-audit."""
    root = _sandbox(tmp_path)
    readme = root / "README.md"
    readme.write_text(readme.read_text().replace("badge/python-3.11", "badge/python-3.99"))
    assert _run(root) != 0


def test_an_invented_number_in_prose_fails_the_build(tmp_path):
    """The reverse check is the half that catches a figure no phrase could guard."""
    root = _sandbox(tmp_path)
    readme = root / "README.md"
    readme.write_text(readme.read_text() + "\n\nA stray claim of 8812 units.\n")
    assert _run(root) != 0


def test_a_missing_metrics_file_is_reported_rather_than_passing(tmp_path):
    root = _sandbox(tmp_path)
    (root / "docs" / "metrics.json").unlink()
    assert _run(root) == 2


def test_a_stale_badge_fails_the_build(tmp_path):
    """A badge is a published claim in the first screen.

    Found by this suite rather than by review: corrupting the test count only
    changed the badge, markdown targets were stripped before either check ran,
    and the build stayed green while the badge advertised a figure the code no
    longer produced.
    """
    root = _sandbox(tmp_path)
    readme = root / "README.md"
    count = _payload()["formatted"]["tests_total"]
    readme.write_text(readme.read_text().replace(f"badge/tests-{count}-", "badge/tests-9001-"))
    assert _run(root) != 0


def test_no_metric_exists_only_to_widen_the_allowed_set(tmp_path):
    """Every metric must be quoted in a checked document, or it is laundering.

    The reverse check passes any number that matches some metric's value. So a
    metric nobody quotes is not neutral: it silently permits that number to
    appear anywhere, which is a hole punched in the one check that catches a
    corrupted figure in a table cell.

    An earlier version of this test asserted only that *some* unanchored metric
    was quoted somewhere, which passed while four metrics appeared in no
    document at all. A re-audit showed that those four let invented sentences
    through. This asserts the property the docstring claims.
    """
    payload = _payload()
    quoted_everywhere = set()
    for name in payload["checked_documents"]:
        body = check_numbers.strip_non_prose((ROOT / name).read_text())
        numbers = set(check_numbers.NUMBER.findall(body))
        quoted_everywhere |= {
            metric for metric, value in payload["formatted"].items() if value in numbers
        }
    unquoted = sorted(set(payload["formatted"]) - quoted_everywhere)
    assert not unquoted, (
        "these metrics are quoted in no checked document, so each one only widens "
        f"the set of numbers the reverse check will accept: {unquoted}"
    )


def test_an_invented_metric_is_caught_by_the_laundering_test(tmp_path):
    """The guard above must actually detect a fabricated metric.

    The previous version did not, which is why this exists: a test that cannot
    fail on the thing it names is worse than no test, because it is counted.
    """
    payload = _payload()
    payload["formatted"]["invented_launderer"] = "73737"
    quoted = set()
    for name in payload["checked_documents"]:
        body = check_numbers.strip_non_prose((ROOT / name).read_text())
        numbers = set(check_numbers.NUMBER.findall(body))
        quoted |= {m for m, v in payload["formatted"].items() if v in numbers}
    assert "invented_launderer" not in quoted


# --------------------------------------------------------------------------
# The collector's red-run guard.
#
# `collect_metrics.read_suite` refuses to publish figures from a run whose
# tests failed, which is the right default and was also a deadlock: the tests
# in this file read the file the collector writes, so they are red by
# construction whenever the figures are stale, and the figures cannot stop
# being stale until the file is written. The guard was narrowed to exempt this
# file alone. These tests pin both halves of that narrowing, because an
# exemption nobody tests is indistinguishable from a hole.
# --------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "tools"))
import collect_metrics  # noqa: E402


def _junit(tests: int, failing: list[tuple[str, str]]) -> str:
    cases = "".join(
        f'<testcase classname="{classname}" name="{name}">'
        f'<failure message="x">x</failure></testcase>'
        for classname, name in failing
    )
    return (
        f'<testsuite name="pytest" tests="{tests}" failures="{len(failing)}" '
        f'errors="0" skipped="0">{cases}</testsuite>'
    )


def _read_suite_with(monkeypatch, tmp_path, junit: str, covered: float = 100.0):
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(junit)
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps({"totals": {"percent_covered": covered}}))
    monkeypatch.setattr(collect_metrics, "JUNIT_PATH", junit_path)
    monkeypatch.setattr(collect_metrics, "COVERAGE_PATH", coverage_path)
    return collect_metrics.read_suite()


def test_a_failing_test_outside_the_receipts_suite_refuses_to_publish(monkeypatch, tmp_path):
    """The guard must still stop figures being published from a broken run."""
    junit = _junit(178, [("tests.test_attribute", "test_the_counterfactual_charge")])
    with pytest.raises(SystemExit) as caught:
        _read_suite_with(monkeypatch, tmp_path, junit)
    message = str(caught.value)
    assert "refusing to publish" in message
    assert "tests/test_attribute.py::test_the_counterfactual_charge" in message


def test_a_failing_receipts_test_does_not_block_collection(monkeypatch, tmp_path, capsys):
    """The one exemption, which is what breaks the deadlock.

    These tests cannot pass before the file they read has been written, so
    treating them as blocking means the file can never be written. Collection
    proceeds and warns; `make verify` re-runs the suite afterwards, so a real
    receipts regression still fails the build.
    """
    junit = _junit(178, [("tests.test_check_numbers", "test_the_checker_passes")])
    suite = _read_suite_with(monkeypatch, tmp_path, junit)
    assert suite["tests_total"] == 178
    assert "receipts tests are red" in capsys.readouterr().err


def test_a_mixed_run_refuses_rather_than_warning(monkeypatch, tmp_path):
    """One exempt failure must not carry a non-exempt one through with it."""
    junit = _junit(
        178,
        [
            ("tests.test_check_numbers", "test_the_checker_passes"),
            ("tests.test_report", "test_the_report_quotes_the_convention"),
        ],
    )
    with pytest.raises(SystemExit) as caught:
        _read_suite_with(monkeypatch, tmp_path, junit)
    assert "test_the_report_quotes_the_convention" in str(caught.value)
    assert "test_the_checker_passes" not in str(caught.value)
