"""Exception types that carry the CLI's exit code distinction structurally.

`AttributionError` means the event log cannot support an attribution, and maps
to exit code 2. A plain `ValueError` means the caller passed something
malformed and maps to 3. `UnattributableShipment` is both, because a shipment
whose timestamps are out of order is a value error to a caller inspecting it
and a refusal to answer at the command line.

Inferring that distinction from the exception class alone is a guess. Carrying
it in the type means the handler reads the author's intent rather than
reconstructing it.
"""


class AttributionError(Exception):
    """Raised when the event log cannot support an attribution at all."""


class UnattributableShipment(AttributionError, ValueError):
    """Raised when one shipment's timestamps cannot be ordered into stages."""
