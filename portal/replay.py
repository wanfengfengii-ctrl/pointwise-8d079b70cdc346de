from portal.edits import AppliedEdit, RecordedEdit, apply_edit
from portal.recording import RecordedRead, RecordedReadAt, RecordingCatalog, ShiftRecording
from portal.table import TableSnapshot, make_initial_snapshot
from portal.windows import WindowRead, read_window


class ReplayHandle:
    def __init__(self, recording: ShiftRecording) -> None:
        self._snapshot = make_initial_snapshot(recording.initial_state, recording.initial_rows)
        self._steps = recording.steps
        self._cursor = 0
        self._pending: dict[str, RecordedRead] = {}
        self._seen = {recording.initial_state}

    @property
    def snapshot(self) -> TableSnapshot:
        return self._snapshot

    def next_event(self) -> AppliedEdit | WindowRead | None:
        while self._cursor < len(self._steps):
            step = self._steps[self._cursor]
            if isinstance(step, RecordedRead):
                if step.window_id in self._pending:
                    raise ValueError(f'window request already pending: {step.window_id}')
                self._pending[step.window_id] = step
                self._cursor += 1
                continue
            if isinstance(step, RecordedReadAt):
                request = self._pending.get(step.window_id)
                if request is None:
                    raise ValueError(f'no request for actual read: {step.window_id}')
                event = read_window(self._snapshot, step.window_id, request.first, request.count)
                del self._pending[step.window_id]
            elif isinstance(step, RecordedEdit):
                snapshot, event = apply_edit(self._snapshot, step)
                if snapshot.state_id in self._seen:
                    raise ValueError('table state identifier already used')
                self._snapshot = snapshot
                self._seen.add(snapshot.state_id)
            else:
                raise ValueError('unknown recording step')
            self._cursor += 1
            return event
        if self._pending:
            raise ValueError('recording ends with pending window requests')
        return None


def open_shift(catalog: RecordingCatalog, recording_id: str) -> tuple[str, int, ReplayHandle]:
    replay = ReplayHandle(catalog.lookup(recording_id))
    return replay.snapshot.state_id, replay.snapshot.row_count, replay
