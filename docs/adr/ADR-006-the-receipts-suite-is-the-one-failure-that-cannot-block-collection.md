# ADR-006: The receipts suite is the one failure that cannot block collection

Status: accepted

## Context

`tools/collect_metrics.py` writes `docs/metrics.json`, and every published figure in this
repository is read from that file rather than typed. It refused to write anything from a
test run with any failure, on the reasoning that figures measured by a broken suite are
not measurements.

That rule is right about every test in this repository except the ones that read
`docs/metrics.json` itself. `tests/test_check_numbers.py` corrupts each published figure
in turn and asserts the build goes red, which means it is red by construction whenever the
figures are stale. Stale figures are exactly the state collection exists to clear. So the
two guards closed on each other: the file could not be written until the tests passed, and
the tests could not pass until the file was written.

The workaround in two sibling repositories was to run pytest with
`--ignore=tests/test_check_numbers.py`, collect, then run the full suite. That works and
is also wrong in a way worth naming: the reduced run reports a smaller test count, so the
`tests_total` figure published from it is not the count the suite actually has. During
this repository's last rewrite it published the reduced run's count rather than the
suite's, and the gap was only caught because a badge check compared the figure against a
later full run. A workaround that silently falsifies a figure is not a workaround for a repository
whose claim is that no figure is typed by hand.

## Decision

Narrow the guard instead of bypassing it. `read_suite` reads the failing test names out of
the JUnit report and refuses when any of them lies outside `tests/test_check_numbers.py`.
When the only failures are inside it, collection proceeds and prints a warning to stderr
naming how many receipts tests are red and saying to re-run the suite afterwards.

The exemption is a file path, not a pattern, and it is pinned by three tests: a failure
outside the suite still refuses and names the test, a failure inside it collects and
warns, and a run with one of each refuses rather than warning.

## Consequences

The deadlock is gone and `tests_total` is read from a run of the whole suite, so the
published count is the count.

What is given up is that the receipts suite no longer gates the file it validates. A real
regression in `tools/check_numbers.py` could therefore be present while
`docs/metrics.json` is rewritten. Three things catch it. `make verify` runs collection and
then the full suite, so the regression fails that build. CI runs the same target on every
push with no flag that skips it. And the suite is the thing being regressed, so a
regression there shows up as a failing test the moment anything runs it, rather than as a
quietly wrong number.

What is not given up is the original property: a figure still cannot be published from a
run in which any part of the measured system is broken. The exemption covers the tests
that check the publishing, not the tests that produce what is published.
