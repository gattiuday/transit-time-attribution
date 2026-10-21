"""Which stage made a delivery late, including the stages a scorecard cannot see.

A carrier on time in full scorecard starts its clock at ship confirm. Every delay
that happened before that moment is outside the window it measures, so a late
delivery caused by a late warehouse release is indistinguishable, in the
scorecard, from one the carrier caused. This package reconstructs the stages from
the event log and attributes the lateness to the one that produced it.
"""

from tta.attribute import Attribution, attribute, attribute_log
from tta.stages import STAGES, Shipment

__all__ = ["STAGES", "Attribution", "Shipment", "attribute", "attribute_log"]
__version__ = "0.3.0"
