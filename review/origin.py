from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from review.history import ValidatedHistory


@dataclass(frozen=True, slots=True)
class OriginSlot:
    origin_position: int | None
    generation: int = 0


@dataclass(frozen=True, slots=True)
class OriginMap:
    states: Mapping[str, tuple[OriginSlot, ...]]

    def slot_at(self, state_id: str, position: int) -> OriginSlot:
        slots = self.states[state_id]
        if type(position) is not int or not 1 <= position <= len(slots):
            raise IndexError('screen position outside the requested state')
        return slots[position - 1]


def build_origin_map(history: ValidatedHistory) -> OriginMap:
    slots = [OriginSlot(position) for position in range(1, history.start.row_count + 1)]
    states = {history.start.state_id: tuple(slots)}
    for edit in history.edits:
        index = edit.position - 1
        match edit.kind:
            case 'insert':
                slots.insert(index, OriginSlot(None))
            case 'delete':
                slots.pop(index)
            case 'move':
                moved = slots.pop(index)
                slots.insert(edit.target - 1, moved)
            case 'rewrite':
                old = slots[index]
                slots[index] = replace(old, generation=old.generation + 1)
        states[edit.after] = tuple(slots)
    return OriginMap(MappingProxyType(states))
