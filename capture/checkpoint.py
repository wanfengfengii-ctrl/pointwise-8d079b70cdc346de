from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from capture.edit_log import EditFact, edit_row_count
from portal.table import is_identifier


@dataclass(frozen=True, slots=True)
class ShiftStart:
    state_id: str
    row_count: int

    def __post_init__(self) -> None:
        if not is_identifier(self.state_id) or type(self.row_count) is not int or self.row_count < 0:
            raise ValueError('invalid shift start')


@dataclass(frozen=True, slots=True)
class CaptureCheckpoint:
    start: ShiftStart
    current_state: str
    row_counts: Mapping[str, int]
    finished: bool = False


def initial_checkpoint(start: ShiftStart) -> CaptureCheckpoint:
    return CaptureCheckpoint(start, start.state_id, MappingProxyType({start.state_id: start.row_count}))


def advance_checkpoint(checkpoint: CaptureCheckpoint, fact: EditFact) -> CaptureCheckpoint:
    if checkpoint.finished:
        raise ValueError('capture is already finished')
    if fact.before != checkpoint.current_state:
        raise ValueError('edit does not continue the capture state')
    count = edit_row_count(fact, checkpoint.row_counts[checkpoint.current_state])
    if fact.after in checkpoint.row_counts:
        raise ValueError('capture state identifier already used')
    counts = dict(checkpoint.row_counts)
    counts[fact.after] = count
    return replace(checkpoint, current_state=fact.after, row_counts=MappingProxyType(counts))


def finish_checkpoint(checkpoint: CaptureCheckpoint) -> CaptureCheckpoint:
    if checkpoint.finished:
        raise ValueError('capture is already finished')
    return replace(checkpoint, finished=True)
