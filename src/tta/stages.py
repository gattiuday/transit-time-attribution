"""The shipment lifecycle as stages, and the one boundary a scorecard starts at.

A shipment passes through five timestamps. Four of the gaps between them are
stages that can be late, and a carrier on time in full scorecard measures
exactly one of them.

    order_created ──┐
                    │  ORDER_TO_RELEASE   warehouse planning and picking
    released ───────┤
                    │  RELEASE_TO_DEPART  waiting for the next departure
    ship_confirm ───┤                     <<< the scorecard's clock starts here
                    │  TRANSIT            the carrier's committed window
    delivered ──────┘

`promised_delivery` sits outside this chain: it is what the customer was told,
and lateness is measured against it rather than against the sum of the stages.

The reason the boundary matters is in the middle stage. A shipment released at
16:05 against a 16:00 cutoff does not depart five minutes late, it waits for
tomorrow's departure, so minutes of warehouse lateness become a day of delivery
lateness. The carrier's own clock, which starts at ship confirm, records a
perfectly normal transit. ADR-003.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import pairwise

from tta.errors import UnattributableShipment

#: The three stages that can be late, in the order they occur. `TRANSIT` is the
#: only one inside a carrier scorecard's window.
STAGES = ("order_to_release", "release_to_depart", "transit")

#: The stage a carrier is contractually responsible for. Named rather than
#: assumed, because every claim in this package about what a scorecard cannot
#: see is a claim about what lies outside it.
CARRIER_STAGE = "transit"

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Shipment:
    """One shipment's timestamps, in seconds since an arbitrary epoch.

    Seconds rather than datetimes on purpose: every quantity this package
    computes is a duration, datetime arithmetic across time zones and daylight
    saving is a source of errors this package has no need to take on, and a
    lane's cutoff is expressed as a local hour which the generator resolves
    once. ADR-002 records what that gives up.

    planned_release and committed_transit are what the plan said, not what
    happened. Lateness at a stage is the actual duration minus the planned one,
    and a stage with no plan cannot be late, only slow.
    """

    shipment_id: str
    lane: str
    order_created: int
    released: int
    ship_confirm: int
    delivered: int
    promised_delivery: int
    planned_release: int
    committed_transit: int

    def as_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> Shipment:
        """Refuse a shipment whose timestamps cannot be ordered into stages.

        Out of order timestamps are common in real transport data: a scanner
        clock drifts, a milestone is backfilled by hand, a carrier EDI message
        arrives with the wrong date. They are refused by name rather than
        silently producing a negative stage duration, which would otherwise show
        up as a stage that saved time.
        """
        sequence = (
            ("order_created", self.order_created),
            ("released", self.released),
            ("ship_confirm", self.ship_confirm),
            ("delivered", self.delivered),
        )
        for (earlier_name, earlier), (later_name, later) in pairwise(sequence):
            if later < earlier:
                raise UnattributableShipment(
                    f"shipment {self.shipment_id} has {later_name} before {earlier_name} "
                    f"({later} < {earlier}); its stages cannot be ordered"
                )
        if self.committed_transit <= 0:
            raise UnattributableShipment(
                f"shipment {self.shipment_id} has a committed transit of "
                f"{self.committed_transit} seconds, so the carrier's window is undefined"
            )
        return self

    @property
    def stage_durations(self) -> dict[str, int]:
        """Actual seconds spent in each stage."""
        return {
            "order_to_release": self.released - self.order_created,
            "release_to_depart": self.ship_confirm - self.released,
            "transit": self.delivered - self.ship_confirm,
        }

    @property
    def delivery_lateness(self) -> int:
        """Seconds later than promised. Negative means early."""
        return self.delivered - self.promised_delivery

    @property
    def carrier_transit_lateness(self) -> int:
        """Seconds the carrier exceeded its committed transit by.

        This is the only quantity a carrier scorecard computes. Negative means
        the carrier beat its commitment, which it routinely does on a shipment
        the warehouse made late, because a missed cutoff hands the carrier a
        fresh full window.
        """
        return self.stage_durations["transit"] - self.committed_transit

    @property
    def release_lateness(self) -> int:
        """Seconds the warehouse released later than planned."""
        return self.released - self.planned_release

    def is_late(self, tolerance_seconds: int) -> bool:
        return self.delivery_lateness > tolerance_seconds

    def carrier_looks_late(self, tolerance_seconds: int) -> bool:
        """Whether a scorecard measuring only transit would flag this shipment."""
        return self.carrier_transit_lateness > tolerance_seconds
