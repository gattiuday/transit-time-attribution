# ADR-008: Grade admissibility beside recovery, because the labels overlap

Status: accepted, narrowing ADR-004 and part of ADR-007

## Context

Every figure in this repository about which stage caused a late delivery rests on a
recovery rate: the attribution names a stage, the generator wrote a cause down, and the
rate is how often the two agree. ADR-004 built the three conventions on that measurement
and ADR-007 reported moving it from 68.6% to 88.4% as the result of fixing the arithmetic.

The measurement does not mean what those documents say it means.

A release that overran by nine hours has also missed the departure it was going to catch.
Both statements are true of the shipment, both describe something that genuinely ran over
plan, and the generator records one of them. Which one depends on nothing more than which
distribution the overrun was drawn from: `warehouse` draws six to twenty hours and
`missed_cutoff` draws the minutes needed to just miss a departure, and a six hour overrun
on a lane with one departure a day misses that departure too.

So the two planted labels are not two causes. As predicates over an event log they are
nested: `missed_cutoff` asserts a release overrun *and* a missed departure, `warehouse`
asserts the release overrun alone. Almost every shipment carrying
either label satisfies both, measured as 96.2% across twelve independent logs, and
`label_is_true` passes both, because both are true. The
label verifier added in response to an earlier audit cannot detect this and never could:
it was built to catch labels that are false, and these are not false.

What follows is that recovery against a single planted label measures how often the
attribution guessed the same true statement the generator happened to record. That is a
property of the generator's draw. Graded instead on whether the named cause is true of the
shipment at all, every convention scores 100.0% on every late delivery, and the convention
spread that ADR-004 and ADR-007 treat as a finding about attribution is the spread in how
often each convention's tiebreak coincides with the generator's.

## Decision

Report both, and label each as what it is.

- **Recovery** stays. It is the number every tool in this space publishes and a reader
  comparing this repository to another needs it. It is reported with the statement that it
  measures agreement with an arbitrary choice.
- **Admissibility** is added: the share of late deliveries whose named cause is true of the
  shipment. `attribute.admissible_causes` computes the set of causes true of a shipment,
  and a test asserts the named cause is in it under every convention, on every late
  delivery.
- **The overlap** is published beside them, so the gap between the two rates is
  attributable rather than mysterious.

Claim 3 in the README is restated around this. The claim that survives is not that the
conventions disagree by nineteen points about the cause; it is that the question "which
upstream stage caused this" has more than one true answer on most late deliveries, so a
tool that returns one answer is returning a convention, and the convention has to travel
with the number.

## Consequences

The repository's headline is untouched. Both upstream stages lie outside the scorecard's
window, so a delivery whose cause is ambiguous between them is unambiguously invisible to
the scorecard, which is the claim this repository exists to make. The ambiguity is
downstream of it.

What is given up is the recovery rate as evidence that the attribution is correct. It was
never that. A reader who wants evidence of correctness should read the admissibility rate,
the identity in ADR-007, and the control cases in `tests/test_grading.py`, and should treat
88.4% as what it is: the rate at which one tiebreak agrees with another.

A generator that planted genuinely disjoint causes would restore recovery as a meaningful
measurement, and that is the obvious next change. It is not made here because making the
labels disjoint means refusing to generate the overlapping case, and the overlapping case
is the one this repository is about. The honest move is to measure the overlap and say so,
not to generate a world in which it does not happen.
