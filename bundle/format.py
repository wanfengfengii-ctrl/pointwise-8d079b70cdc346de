import json
from dataclasses import dataclass

from capture.checkpoint import ShiftStart
from capture.edit_log import EditFact
from capture.observations import CapturedWindow, ObservedRow
from capture.timeline import TimelineEntry
from portal.table import is_identifier


@dataclass(frozen=True, slots=True)
class BundlePayload:
    recording_id: str
    start: ShiftStart
    records: tuple[TimelineEntry, ...]


def json_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f'duplicate JSON field {key!r}')
        values[key] = value
    return values


def _invalid_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant {value!r}')


def load_json(raw: bytes) -> object:
    if type(raw) is not bytes:
        raise ValueError('fixed content must be bytes')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except RecursionError as exc:
        raise ValueError('fixed content nests too deeply') from exc


def encode_record(entry: TimelineEntry) -> dict[str, object]:
    if isinstance(entry, EditFact):
        return {'type': 'edit', 'kind': entry.kind, 'before': entry.before, 'after': entry.after,
                'position': entry.position, 'target': entry.target}
    if isinstance(entry, CapturedWindow):
        return {'type': 'window', 'window_id': entry.window_id, 'state_id': entry.state_id,
                'rows': [[row.position, row.mm] for row in entry.rows]}
    raise ValueError('unknown fixed content record')


def encode_payload(payload: BundlePayload) -> bytes:
    return json_bytes({'recording_id': payload.recording_id,
                       'start': {'state_id': payload.start.state_id, 'row_count': payload.start.row_count},
                       'records': [encode_record(entry) for entry in payload.records]})


def _fields(data: object, fields: set[str], label: str) -> dict:
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError(f'invalid {label} fields')
    return data


def decode_record(data: object) -> TimelineEntry:
    if not isinstance(data, dict):
        raise ValueError('record must be an object')
    if data.get('type') == 'edit':
        edit = _fields(data, {'type', 'kind', 'before', 'after', 'position', 'target'}, 'edit')
        if any(not is_identifier(edit[key]) for key in ('kind', 'before', 'after')):
            raise ValueError('invalid edit identifiers')
        if type(edit['position']) is not int:
            raise ValueError('invalid edit position field')
        target = edit['target']
        if target is not None and type(target) is not int:
            raise ValueError('invalid edit target field')
        return EditFact(edit['kind'], edit['before'], edit['after'], edit['position'], target)
    if data.get('type') == 'window':
        window = _fields(data, {'type', 'window_id', 'state_id', 'rows'}, 'window')
        if not is_identifier(window['window_id']) or not is_identifier(window['state_id']):
            raise ValueError('invalid window identifiers')
        if not isinstance(window['rows'], list):
            raise ValueError('window rows must be an array')
        rows = []
        for row in window['rows']:
            if not isinstance(row, list) or len(row) != 2 or any(type(value) is not int for value in row):
                raise ValueError('observed row requires integer position and millimetres')
            rows.append(ObservedRow(*row))
        return CapturedWindow(window['window_id'], window['state_id'], tuple(rows))
    raise ValueError('unknown fixed content record type')


def decode_payload(raw: bytes) -> BundlePayload:
    data = _fields(load_json(raw), {'recording_id', 'start', 'records'}, 'payload')
    if not is_identifier(data['recording_id']) or not isinstance(data['records'], list):
        raise ValueError('invalid recording identifier or records array')
    start = _fields(data['start'], {'state_id', 'row_count'}, 'shift start')
    return BundlePayload(data['recording_id'], ShiftStart(start['state_id'], start['row_count']),
                         tuple(decode_record(entry) for entry in data['records']))
