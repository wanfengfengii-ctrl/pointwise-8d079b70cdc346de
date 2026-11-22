from dataclasses import dataclass

from bundle.format import BundlePayload
from capture.checkpoint import ShiftStart
from capture.edit_log import EditFact, edit_row_count
from capture.observations import CapturedWindow, validate_window


class InvalidHistory(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedHistory:
    start: ShiftStart
    edits: tuple[EditFact, ...]
    windows: tuple[tuple[int, CapturedWindow], ...]


def validate_history(payload: BundlePayload) -> ValidatedHistory:
    start = payload.start
    current = start.state_id
    counts = {current: start.row_count}
    edits = []
    windows = []
    for sequence, entry in enumerate(payload.records, start=1):
        if isinstance(entry, CapturedWindow):
            windows.append((sequence, entry))
            continue
        if not isinstance(entry, EditFact):
            raise InvalidHistory(f'invalid entry at event {sequence}')
        if entry.before != current:
            raise InvalidHistory(f'edit at event {sequence} starts at {entry.before!r}, expected {current!r}')
        if entry.after in counts:
            raise InvalidHistory(f'reused state {entry.after!r} at event {sequence}')
        try:
            counts[entry.after] = edit_row_count(entry, counts[current])
        except ValueError as exc:
            raise InvalidHistory(f'invalid edit at event {sequence}: {exc}') from exc
        edits.append(entry)
        current = entry.after

    for sequence, window in windows:
        if window.state_id not in counts:
            raise InvalidHistory(f'unknown actual state {window.state_id!r} at event {sequence}')
        try:
            validate_window(window, counts[window.state_id])
        except ValueError as exc:
            raise InvalidHistory(f'invalid window at event {sequence}: {exc}') from exc
    return ValidatedHistory(start, tuple(edits), tuple(windows))
