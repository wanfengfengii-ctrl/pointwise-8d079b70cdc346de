from dataclasses import dataclass

from capture.observations import CapturedWindow, ObservedRow
from review.origin import OriginMap


@dataclass(frozen=True, slots=True)
class EligibleObservation:
    origin_position: int
    mm: int
    state_id: str
    window_id: str
    screen_position: int
    capture_sequence: int


def qualify_observation(origins: OriginMap, sequence: int, window: CapturedWindow,
                        row: ObservedRow) -> EligibleObservation | None:
    slot = origins.slot_at(window.state_id, row.position)
    if slot.origin_position is None or slot.generation != 0:
        return None
    return EligibleObservation(slot.origin_position, row.mm, window.state_id, window.window_id,
                               row.position, sequence)
