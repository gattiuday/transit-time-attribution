# ADR-005: What a generated event log can and cannot establish

Status: accepted

## Context

Every number here is measured against a seeded generator rather than a real transport
log. That is a deliberate trade with a boundary, and a reviewer is entitled to know where
it falls before deciding what the numbers are worth.

The generator is not a convenience. The quantity this tool exists to produce, which stage
caused a late delivery, is exactly the quantity no transport system records. There is no
real log with a labelled answer, so grading the attribution at all requires planting one.

## Claims the fixture fully establishes

Properties of the arithmetic and of the lifecycle, identical against real data:

- **A carrier scorecard cannot see a delay that ends before ship confirm.** This follows
  from the definition of the window, not from the data. The 73.0% upstream share is a
  property of this log; that the share is unmeasurable from a scorecard is general.
- **A missed cutoff is a step, not a proportional cost.** A release one minute past the
  last departure costs the whole gap to the next one. A property of timetables.
- **Lanes with different departure frequency are not comparable on delivered service.**
  Every lane in the fixture is generated with the same mix of planted causes, so the
  carriers are equally good by construction, and the three departure lane still shows
  26.6% on the three departure lane against 36.8% late on the others. The mechanism transfers; the sizes do not.
- **No single cause convention recovers every planted cause**, because 87.4% of late
  deliveries have more than one stage over plan. Structural.
- **A coarser clock loses the attribution silently.** It reports fewer late shipments
  rather than an error.
- **The resolution arithmetic.** A rate over 21 flagged shipments cannot separate a perfect
  rate from one five points below it, whatever the flags were. This entry used to read "the
  resolution floor arithmetic" and the floor was one over the sample size, which is a
  statement about what a rate can express and not about sampling error. An audit pointed
  out that it is far narrower than a confidence interval and that the module was using it
  as though it were one: at 21 flags it put the floor at 5.09% while the Wilson interval is
  12.50%. Both are published now and the wider one decides, which moved the sample the
  claim needs from roughly 2000 shipments to 8000. What the fixture establishes is the
  arithmetic, not either bound's adequacy for a particular decision.
- **The exit code contract.** Behavioural.

## Claims the fixture establishes only conditionally

- **The 73.0% upstream share.** It follows directly from the planted cause mix, which was
  chosen to have enough lateness of each kind to measure. A real operation with a tight
  warehouse and a loose timetable would show far less; one with a 14:00 cutoff and a
  struggling pick line would show more. What transfers is that the share is not zero and
  is not visible from the scorecard.
- **The scorecard's precision of 92.6% and 27.0% recall.** The precision is high because the
  generator's carrier overruns are large enough to breach the committed window every time.
  Real carrier lateness includes marginal misses that a tolerance absorbs, so real
  precision would be lower and real recall lower still. The shape, precise about what it
  flags and blind to most of the problem, is what the measurement supports.
- **The cost of a coarser clock.** Depends on how near the misses are, which depends on
  how tightly the warehouse runs against the cutoff.

## The claim that needs real data

**That a transport team acting on this attribution would make better decisions.** The tool
says the scorecard misses most of the lateness. It does not know what the warehouse could
have done differently, what a later cutoff would cost to negotiate, or whether the carrier
would accept a wider window. Those are the decisions, and none of them is in this data.

The honest statement to a hiring manager: this proves the scorecard's window excludes most
of the lateness and quantifies the exclusion on a log where the answer is known. It does
not prove any particular operation has that problem, and this repository does not claim it.

## What a real log would break that this one does not

Real transport data is dirtier than coarse. A scanner clock drifts. A milestone is
backfilled by hand two days later. A carrier EDI message arrives with the wrong date.
Those produce timestamps that are out of order, and this package refuses those shipments
by name rather than repairing them.

That refusal is correct and it is also a selection effect nobody has measured here. If
out of order timestamps are more common on shipments that went badly, which is plausible
because a chaotic shipment attracts manual intervention, then refusing them biases the
attribution toward the shipments that went smoothly. The fixture produces no out of order
timestamps at all, so this repository cannot measure that bias and does not pretend to.
It is the first thing to check against a real log.
