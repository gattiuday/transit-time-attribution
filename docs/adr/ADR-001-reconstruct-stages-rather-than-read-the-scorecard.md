# ADR-001: Reconstruct the stages from the event log rather than reading the scorecard

Status: accepted

## Context

Every transport management system already produces a carrier on time in full number.
It is cheap, it is comparable across carriers, and it is what appears in a quarterly
business review. The obvious thing to build on top of it is a better scorecard.

That cannot work, and the reason is structural rather than a matter of accuracy. A
carrier scorecard measures from ship confirm to delivery against a committed transit
window. Every delay that happened before ship confirm is outside the interval it
measures. It is not measured imprecisely; it is not measured.

So a late delivery caused by a warehouse that released after the day's last departure
appears in the scorecard as a normal transit, because the carrier received the shipment
the next morning and delivered it inside its window from there. The scorecard is not
wrong about the carrier. It is answering a different question from the one a transport
team thinks it is answering.

## Decision

Reconstruct the stages from the event log: order created, released, ship confirm,
delivered. Compute lateness per stage against the plan for that stage, and report which
stage produced the delivery lateness. Carry the scorecard's own number alongside, so the
two can be compared on the same shipments.

## Alternatives considered

**Widen the carrier's window to start at order creation.** This is sometimes proposed as
"door to door OTIF". It makes the carrier accountable for the warehouse, which no carrier
will sign, and it still produces one number with no attribution inside it. The problem is
not that the window is too narrow; it is that one number cannot carry three causes.

**Compare actual transit against a lane median rather than a commitment.** This detects a
carrier that is slower than its peers and still says nothing about the stages before it.
It also moves with the mix of shipments on the lane, which is the failure mode of a
sibling repository in this portfolio.

**Ask the warehouse.** A release timestamp exists; a reason code usually does not, and
where one does it is entered by the person whose performance it describes.

## Consequences

The output is three numbers and a convention rather than one number, and a transport team
has to decide which conversation to have rather than being handed a carrier's name.

It needs an event log with four timestamps per shipment, which is more than a scorecard
needs and less than most transport systems already hold. Where a timestamp is missing or
out of order the shipment is refused by name rather than attributed on three timestamps,
because a negative stage duration would otherwise appear as a stage that saved time.

The attribution is only as good as the plan it compares against. A stage with no plan
cannot be late, only slow, and this is why `planned_release` and `committed_transit` are
required inputs rather than derived from the data.
