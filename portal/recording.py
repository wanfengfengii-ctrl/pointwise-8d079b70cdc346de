import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable

from portal.edits import RecordedEdit
from portal.table import is_identifier, make_initial_snapshot


@dataclass(frozen=True, slots=True)
class RecordedRead:
    window_id: str
    first: int
    count: int

    def __post_init__(self) -> None:
        if not is_identifier(self.window_id):
            raise ValueError('invalid requested window identifier')
        if type(self.first) is not int or type(self.count) is not int:
            raise ValueError('window bounds must be integers')
        if self.first < 1 or self.count < 1:
            raise ValueError('window bounds must be positive')


@dataclass(frozen=True, slots=True)
class RecordedReadAt:
    window_id: str

    def __post_init__(self) -> None:
        if not is_identifier(self.window_id):
            raise ValueError('invalid read window identifier')


@dataclass(frozen=True, slots=True)
class ShiftRecording:
    recording_id: str
    initial_state: str
    initial_rows: tuple[int, ...]
    steps: tuple[RecordedRead | RecordedReadAt | RecordedEdit, ...]


class RecordingCatalog:
    def __init__(self, recordings: Iterable[ShiftRecording]) -> None:
        indexed = {}
        for recording in recordings:
            if not is_identifier(recording.recording_id) or recording.recording_id in indexed:
                raise ValueError('invalid or duplicate recording identifier')
            make_initial_snapshot(recording.initial_state, recording.initial_rows)
            indexed[recording.recording_id] = recording
        self._recordings = MappingProxyType(indexed)

    def lookup(self, recording_id: str) -> ShiftRecording:
        if not is_identifier(recording_id) or recording_id not in self._recordings:
            raise KeyError(f'unknown recording {recording_id!r}')
        return self._recordings[recording_id]


def _step(raw: object) -> RecordedRead | RecordedReadAt | RecordedEdit:
    if not isinstance(raw, dict):
        raise ValueError('recording step must be an object')
    operation = raw.get('op')
    if operation == 'request' and raw.keys() == {'op', 'window', 'first', 'count'}:
        return RecordedRead(raw['window'], raw['first'], raw['count'])
    if operation == 'read' and raw.keys() == {'op', 'window'}:
        return RecordedReadAt(raw['window'])
    fields = {'op', 'before', 'after', 'position'}
    if operation == 'move':
        fields.add('target')
    if operation in ('insert', 'rewrite'):
        fields.add('mm')
    if operation in ('insert', 'delete', 'move', 'rewrite') and raw.keys() == fields:
        return RecordedEdit(operation, raw['before'], raw['after'], raw['position'],
                            raw.get('target'), raw.get('mm'))
    raise ValueError('invalid recording step fields or operation')


def _recording(raw: object) -> ShiftRecording:
    fields = {'recording_id', 'initial_state', 'initial_rows', 'events'}
    if not isinstance(raw, dict) or raw.keys() != fields:
        raise ValueError('invalid recording fields')
    if not isinstance(raw['initial_rows'], list) or not isinstance(raw['events'], list):
        raise ValueError('recording rows and events must be arrays')
    return ShiftRecording(raw['recording_id'], raw['initial_state'], tuple(raw['initial_rows']),
                          tuple(_step(item) for item in raw['events']))


def load_recordings(path: str | Path) -> RecordingCatalog:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.keys() != {'recordings'}:
        raise ValueError('recording catalog requires a recordings field')
    if not isinstance(data['recordings'], list):
        raise ValueError('recordings must be an array')
    return RecordingCatalog(_recording(item) for item in data['recordings'])
