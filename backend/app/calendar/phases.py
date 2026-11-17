"""Calendar business phases over the existing appointment lifecycle.

The immutable event snapshot stores the finer business phase, as it already
stores qualification. Existing clients and calling policies retain the same
four lifecycle states; no data migration or history rewrite is necessary.
"""
from typing import Literal

Phase = Literal['booked', 'confirmed', 'sold', 'cancelled', 'invalid', 'non_compliant', 'completed', 'no_show']
LIFECYCLE = {
    'booked': 'booked', 'confirmed': 'booked', 'sold': 'completed',
    'cancelled': 'cancelled', 'invalid': 'cancelled', 'non_compliant': 'cancelled',
    'completed': 'completed', 'no_show': 'no_show',
}

# Only the latest event may supply the current phase. An older application
# editing an appointment remains compatible and cannot resurrect a stale phase.
PHASE_SQL = """CASE WHEN latest.details->'after'->>'status'=a.status
    THEN coalesce(latest.details->'after'->>'phase',a.status) ELSE a.status END"""


def next_phase(status, requested=None, previous=None):
    if requested is not None:
        if LIFECYCLE[requested] != status:
            raise ValueError('La phase et le statut du rendez-vous ne correspondent pas.')
        return requested
    return previous if LIFECYCLE.get(previous) == status else status
