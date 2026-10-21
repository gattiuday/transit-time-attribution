# ADR-004: Report the convention beside every cause, because overlap is the norm

Status: accepted

## Context

A release that overran by six hours has also missed the day's last departure. Both stages
are over plan. Both statements are true. Asking which one "caused" the late delivery is
asking a question the data cannot answer, because the second is a consequence of the first
and the first is not sufficient on its own: a six hour overrun on a lane with a later
cutoff would have cost nothing.

On this repository's fixture, 62.8% of late deliveries have more than one stage over plan.
That is not an artefact of the generator. It is what a step function downstream of a
continuous overrun produces.

## Decision

Implement three conventions, report which one produced a number, and publish what each
one costs.

- **first_cause** names the earliest stage over plan.
- **largest_cause** names the stage with the biggest overrun.
- **proportional** splits across every stage over plan.

`largest_cause` is the default because it is the one a reader expects, not because it is
right.

## What the measurement showed

Graded against the planted cause across twelve independent logs:

| Convention | Recovery | Loses most on |
| --- | --- | --- |
| first_cause | 72.4% | missed cutoffs, which it blames on the warehouse |
| largest_cause | 67.3% | warehouse overruns, which it blames on the departure wait |
| proportional | 67.3% | the same as largest_cause, since it names the largest for a single cause |

**The two single cause conventions fail on opposite groups, and neither clears four
fifths.** `first_cause` recovers every warehouse overrun and sends every missed cutoff to
the warehouse as well, because the small release overrun came first. `largest_cause`
recovers every missed cutoff and sends most warehouse overruns to the departure wait,
because a missed departure is mechanically larger than the overrun that caused it.

## The claim that survives the convention

The headline does not depend on this choice at all, and that is load bearing rather than
fortunate. Both `order_to_release` and `release_to_depart` lie outside a carrier
scorecard's window, so which of them a convention names cannot change how much of the
lateness the scorecard misses. The upstream share is identical under all three, and
`test_the_upstream_share_is_the_same_under_every_convention` fails if that ever stops
being true.

So this repository makes a strong claim about how much a scorecard cannot see, and a
scoped one about which upstream team to talk to.

## Consequences

Every output names its convention, and the verdict warns when the overlap share is high,
which on realistic data it always is.

A user who wants one cause per shipment can have one. They cannot have one that is
correct more than about three quarters of the time, and the tool says so rather than
letting the number imply otherwise.
