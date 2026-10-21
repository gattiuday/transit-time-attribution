# ADR-002: Timestamps are seconds, and granularity bounds what can be attributed

Status: accepted

## Context

Two decisions about time, taken together because they interact.

First, representation. Every quantity this package computes is a duration. Datetimes
would bring time zones and daylight saving into arithmetic that does not need them, and a
lane's cutoff is a local hour that only has to be resolved once, when the log is built.

Second, and more importantly: the attribution depends on knowing whether a release landed
before or after a cutoff. That is a question about minutes. A transport system that
records milestones to the hour cannot answer it for a six minute miss, and one that
records to the day cannot answer it at all.

## Decision

Timestamps are integer seconds since an arbitrary epoch. `resolution.coarsen` rounds a
shipment to a coarser grid so the cost of a coarser clock can be measured rather than
assumed, and the rounding **mode** is a parameter rather than a constant.

## Why the mode is a parameter

Because it is not neutral, and the measurement says so. Flooring every milestone moves a
release earlier, which hides a near miss. Rounding to nearest moves half of them later,
which invents one.

On a daily clock those two choices produce 631 and 970 late shipments from the same
underlying data, and an upstream share of 63.9% against 75.5%. That is a 54% difference in
the headline count, decided by a convention that no transport system records anywhere.

`experiments/exp04` publishes the whole table, including the result that an hourly clock
costs almost nothing. That was not the expected answer and is reported as measured.

## Consequences

A user whose system records to the day will get a number from this tool and should not
act on it. The tool says so: the granularity sweep is a subcommand, not a footnote.

Seconds since an epoch means the fixture is not human readable, and a reviewer reading
the CSV sees large integers rather than dates. That is a real cost and the alternative
was worse.

## What this gives up

Real transport data has worse problems than granularity: a scanner clock that drifts, a
milestone backfilled by hand two days later, a carrier EDI message with the wrong date.
Those produce timestamps that are out of order rather than merely coarse, and this package
refuses those shipments rather than repairing them. ADR-005 carries what that costs.
