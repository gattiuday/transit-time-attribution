# ADR-003: Charge a missed departure by counterfactual, not by the wait

Status: accepted, after getting it wrong twice

## Context

A shipment waits between release and departure whether or not anything went wrong,
because departures leave on a schedule. The question is what portion of that wait is
anybody's fault.

This is the stage the whole package is about, and it is where the step function lives.
A shipment released at 16:05 against a 16:00 cutoff on a lane with one departure a day
does not leave five minutes late. It leaves twenty four hours late. The carrier then
receives it the next morning with a fresh full window and delivers comfortably inside it.

## Two wrong answers, in order

**Charge the whole wait.** This blames the warehouse for the timetable. A shipment
released at 06:00 on a lane whose only departure is at 16:00 waits ten hours and did
nothing wrong.

**Charge the wait above a fixed floor.** This was the second version. It subtracts the
handling time every shipment incurs and charges the rest. It is better and still wrong,
because an *early* release can land in an unlucky part of the day just as easily as a
late one. `experiments/exp01` caught this: shipments whose planted cause was an
infeasible plan, with every stage inside its plan, were being attributed to a departure
wait they had not caused, in a confusion matrix that existed precisely to catch this.

## Decision

Charge the counterfactual. The cost of the departure stage is

    actual ship confirm  minus  the departure an on plan release would have caught

A release that misses nothing costs nothing here, however long it then waits. A release
five minutes late that misses the day's last departure costs the entire gap to tomorrow's.
A release *earlier* than plan produces a negative number, which is clipped to zero rather
than credited, because beating the plan does not earn back time the timetable controls.

Computing it requires the lane's departure schedule, which is a declared operational fact
living in `config` alongside the cutoff hour. It is passed into the attribution rather
than derived there, so the arithmetic holds no knowledge of any particular lane.

## Consequences

The charge is a step, and the step size is the gap between departures. That makes two
lanes with identical carriers and identical warehouse error rates produce very different
delivered service: on this repository's fixture, 36.8% late on
the single departure lanes against 22.8% on the lane with three, with the carrier caused
rate identical across all three to within a tenth of a point.

The lane with the most departures therefore shows the best delivered service **and** the
largest carrier share of its own lateness, 40.1% on the lane with three against 24.4% of
its own lateness on the single departure lanes. A scorecard comparing
carriers across lanes of different departure frequency is comparing timetables, and the
carrier on the most forgiving schedule looks best whatever it does. `experiments/exp03`.

## What this still cannot do

It assumes the departure schedule is fixed and known. A lane with ad hoc capacity, or one
where a shipment can be re-planned onto a different service, breaks the counterfactual:
there is no single departure the shipment "would have" caught. The tool would need the
capacity plan, which is a different data source and a different repository.
