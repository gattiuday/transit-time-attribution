# ADR-007: Charge the departure net of the overrun that forced it

Status: accepted, replacing part of ADR-003

## Context

ADR-003 established that a missed departure is charged by counterfactual: the departure
this shipment actually caught, against the departure it would have caught had it released
on plan. That decision stands. What it did not say is how much of the resulting
displacement belongs to the departure, and the first implementation answered all of it.

Combined with a release charged its own overrun, the overrun was billed twice. A release
nine hours late on a lane with one departure a day pushes the departure a full day; the
decomposition charged nine hours to the warehouse and twenty four to the departure, for a
delivery that was twelve hours late. `experiments/exp06` reconstructs the defective charge
and runs it beside the current one over twelve independent logs: the charges exceeded
the lateness on 91.2% of late deliveries and totalled 2.05 times it.

Nothing in the repository compared the charges against the lateness they explained, so a
full test suite, a green CI run, three ADRs and a receipts system that verifies every
published figure all passed over it. An audit found it by adding three numbers up.

The damage was not confined to the arithmetic. A missed departure is larger than the
overrun that caused it only because the overrun had been added to it, so `largest_cause`
named the departure wait for all but 391 of 5428 planted warehouse overruns. That
produced a recovery of 68.6%, and the repository wrote the shortfall up as a
structural ceiling: the README said no convention clears four fifths, the decision records
said the attribution cannot name a single cause and no version of it will, and a test
pinned the recovery inside a band in the sixties and seventies, so the ceiling could not
move without someone noticing. The claim that the data could not answer the question was itself an artefact of
the arithmetic. That is a worse failure than a wrong number, because a wrong number is
corrected by the next measurement and a wrong limitation is cited as a reason not to
measure again.

## Decision

Charge the departure the displacement net of the release overrun: the wait that releasing
on plan would not have avoided. The three charges then satisfy an identity.

    delivery_lateness = order_to_release + release_to_depart + transit - promise_slack

where the slack is the buffer the promise holds over the plan, recovered by subtraction
because nothing in an event log records it.

**That identity is algebra, not evidence, and this ADR said otherwise.** It claimed
`attribute.residual` was verified "for every shipment in the fixture rather than for an
example", and a later audit substituted random integers for the counterfactual departure and
the committed transit and watched it still close on every row: both terms appear in the
charges and again in the slack with opposite signs, so they cancel, and `residual` is the
constant zero for every possible input. Iterating a constant two thousand times verifies
nothing.

The pairing that does not cancel is the one this decision is about. The two upstream charges
must sum to the departure displacement, which is computed from the timestamps rather than
from the charges, so a change to either that does not preserve their sum shows up.
`attribute.displacement_residual` is that quantity, `tests/test_attribute.py` asserts it is
zero over every shipment, and a mutation test reintroduces the double charge and checks the
assertion goes red. That is the invariant to cite; the identity above is a consequence of the
definitions and is kept because it is how the slack term was found, not because it tests
anything.

Negative slack is now the definition of `infeasible_plan` rather than an inference from a
late delivery with no stage over plan. The two sets are the same set only while the
arithmetic is right, and the inference made that branch the silent destination for anything
the decomposition could not explain. A late shipment with a feasible plan and nothing over
plan is refused by name instead.

Blame is a second decomposition, not the same one with the signs dropped. `stage_lateness`
reconciles and carries signs, so a release that beat its plan is a credit; `stage_overruns`
decides which stage is over plan and floors both upstream terms at zero. A release four
hours early waits four hours longer for the same departure, which the reconciling charges
record as a credit spent and blame must record as nothing over plan at all. Conflating the
two is how the double charge got in: the release was charged what happened and the
departure was charged a counterfactual, which are not the same measure and do not belong in
one sum.

## Consequences

Recovery of the planted cause under `largest_cause` moves from 68.6% to 88.4%. The
convention still matters, and it matters more: the two naming conventions now disagree by
about nineteen points rather than five, because the double charge used to swamp the
difference between them. What survives of the old limitation is smaller and real. On a lane
with one departure a day a nine hour overrun still leaves fifteen hours of waiting that
releasing on plan would have avoided, so `largest_cause` names the timetable rather than
the warehouse, and `first_cause` names the warehouse and loses every missed cutoff.

The headline is unchanged at 73.0%, because both upstream stages lie outside the
scorecard's window and netting moves lateness between them rather than out of them. That is
the claim this repository is for, and it was the one claim the defect did not touch.

Three documents and three tests asserted the ceiling. All of them have been changed rather
than deleted, and each says what it used to say and why that was wrong, because a repository
whose corrections are invisible is asking to be trusted rather than read.
