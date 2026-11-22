from capture.checkpoint import (CaptureCheckpoint, ShiftStart, advance_checkpoint,
                                finish_checkpoint, initial_checkpoint)
from capture.edit_log import capture_edit_fact
from capture.observations import capture_observation
from capture.timeline import CaptureTimeline, TimelineEntry
from portal.edits import AppliedEdit
from portal.table import is_identifier
from portal.windows import WindowRead


class CaptureSession:
    def __init__(self, recording_id: str, start: ShiftStart) -> None:
        if not is_identifier(recording_id):
            raise ValueError('invalid capture recording identifier')
        self._recording_id = recording_id
        self._checkpoint = initial_checkpoint(start)
        self._timeline = CaptureTimeline()

    @property
    def recording_id(self) -> str:
        return self._recording_id

    @property
    def checkpoint(self) -> CaptureCheckpoint:
        return self._checkpoint

    @property
    def records(self) -> tuple[TimelineEntry, ...]:
        return self._timeline.snapshot()

    def _accept(self, event: AppliedEdit | WindowRead) -> None:
        checkpoint = self._checkpoint
        if checkpoint.finished:
            raise ValueError('capture is already finished')
        if isinstance(event, AppliedEdit):
            entry = capture_edit_fact(event)
            checkpoint = advance_checkpoint(checkpoint, entry)
        elif isinstance(event, WindowRead):
            if not is_identifier(event.state_id) or event.state_id not in checkpoint.row_counts:
                raise ValueError('observation has an unknown actual state')
            entry = capture_observation(event, checkpoint.row_counts[event.state_id])
        else:
            raise ValueError('capture accepts only portal edits and actual windows')
        self._timeline.append(entry)
        self._checkpoint = checkpoint

    def _finish(self) -> None:
        checkpoint = finish_checkpoint(self._checkpoint)
        self._timeline.freeze()
        self._checkpoint = checkpoint


def start_capture(recording_id: str, state_id: str, row_count: int) -> CaptureSession:
    return CaptureSession(recording_id, ShiftStart(state_id, row_count))


def capture_window(session: CaptureSession, event: AppliedEdit | WindowRead) -> None:
    session._accept(event)


def finish_capture(session: CaptureSession) -> None:
    session._finish()
