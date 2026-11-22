"""Certified source material and the certified bundle payload.

The portal is the trusted capture boundary.  While the replay runs it produces
a *source material*: the recording identity, the attempt, the shift start and
row count, every edit fact and the identity of every actual read window, plus
the normal end state.  Each source event and the end are authenticated by the
portal callback over a hash chain, so removing, reordering or retargeting any
event invalidates the chain.  A handover clerk then picks windows; the picked
windows keep their source sequence but unselected window bodies never enter the
bundle.
"""
import base64
import binascii
import hashlib
from dataclasses import dataclass

from bundle.format import decode_record, encode_record, json_bytes, load_json
from capture.checkpoint import ShiftStart
from capture.edit_log import EditFact, edit_row_count
from capture.observations import CapturedWindow
from portal.table import is_identifier


_EVENT_TAG = b'\x00event\x00'
_END_TAG = b'\x00end\x00'


def _integer(value: object) -> bool:
    return type(value) is int


def _digest_hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and value.isascii()


@dataclass(frozen=True, slots=True)
class EditBinding:
    sequence: int
    kind: str
    before: str
    after: str
    position: int
    target: int | None = None


@dataclass(frozen=True, slots=True)
class WindowBinding:
    sequence: int
    window_id: str
    state_id: str
    digest: str


SourceEvent = EditBinding | WindowBinding


@dataclass(frozen=True, slots=True)
class SourceMaterial:
    recording_id: str
    attempt_id: str
    start: ShiftStart
    final_state: str
    events: tuple[SourceEvent, ...]

    @property
    def sequence(self) -> int:
        return len(self.events)

    def event(self, sequence: int) -> SourceEvent | None:
        for event in self.events:
            if event.sequence == sequence:
                return event
        return None


@dataclass(frozen=True, slots=True)
class CertRecord:
    attempt_id: str
    source_sequence: int
    entry: object
    source_evidence: str


@dataclass(frozen=True, slots=True)
class CertPayload:
    recording_id: str
    start: ShiftStart
    attempt_id: str
    records: tuple[CertRecord, ...]
    material: SourceMaterial
    proofs: tuple[tuple[int, str], ...]
    end_proof: str


def window_digest(window: CapturedWindow) -> str:
    return hashlib.sha256(json_bytes({
        'window_id': window.window_id,
        'state_id': window.state_id,
        'rows': [[row.position, row.mm] for row in window.rows],
    })).hexdigest()


def edit_binding(sequence: int, entry: EditFact) -> EditBinding:
    return EditBinding(sequence, entry.kind, entry.before, entry.after, entry.position, entry.target)


def window_binding(sequence: int, window: CapturedWindow) -> WindowBinding:
    return WindowBinding(sequence, window.window_id, window.state_id, window_digest(window))


def _event_data(event: SourceEvent) -> list[object]:
    if isinstance(event, EditBinding):
        return ['edit', event.sequence, event.kind, event.before, event.after,
                event.position, event.target]
    if isinstance(event, WindowBinding):
        return ['window', event.sequence, event.window_id, event.state_id, event.digest]
    raise ValueError('unknown source event')


def _start_data(material: SourceMaterial) -> dict[str, object]:
    return {'state_id': material.start.state_id, 'row_count': material.start.row_count}


def _base(material: SourceMaterial) -> bytes:
    return json_bytes({
        'recording_id': material.recording_id,
        'attempt_id': material.attempt_id,
        'start': _start_data(material),
    })


def _genesis(material: SourceMaterial) -> str:
    return hashlib.sha256(b'harbour-source-chain-v1\x00' + _base(material)).hexdigest()


def _next_chain(previous: str, event: SourceEvent) -> str:
    return hashlib.sha256(previous.encode('ascii') + b'\x00' + json_bytes(_event_data(event))).hexdigest()


def chain_digests(material: SourceMaterial) -> tuple[str, ...]:
    """Chain value *before* each event, in source order."""
    previous = _genesis(material)
    values = []
    for event in material.events:
        values.append(previous)
        previous = _next_chain(previous, event)
    return tuple(values)


def final_chain(material: SourceMaterial) -> str:
    previous = _genesis(material)
    for event in material.events:
        previous = _next_chain(previous, event)
    return previous


def event_message(material: SourceMaterial, position: int) -> bytes:
    """Message signed for the event at 1-based source position *position*."""
    previous = chain_digests(material)[position - 1]
    event = material.events[position - 1]
    return _base(material) + _EVENT_TAG + json_bytes({
        'sequence': event.sequence,
        'previous': previous,
        'event': _event_data(event),
    })


def end_message(material: SourceMaterial) -> bytes:
    return _base(material) + _END_TAG + json_bytes({
        'final_state': material.final_state,
        'count': material.sequence,
        'chain': final_chain(material),
    })


def encode_material(material: SourceMaterial) -> bytes:
    return json_bytes({
        'recording_id': material.recording_id,
        'attempt_id': material.attempt_id,
        'start': _start_data(material),
        'final_state': material.final_state,
        'events': [_event_data(event) for event in material.events],
    })


def _source_event(raw: object) -> SourceEvent:
    if not isinstance(raw, list) or not raw:
        raise ValueError('source event must be a non-empty array')
    kind = raw[0]
    if kind == 'edit' and len(raw) == 7:
        _, sequence, operation, before, after, position, target = raw
        if not _integer(sequence) or sequence < 1:
            raise ValueError('source edit sequence must be a positive integer')
        if not is_identifier(operation) or not is_identifier(before) or not is_identifier(after):
            raise ValueError('invalid source edit identifiers')
        if not _integer(position) or position < 1:
            raise ValueError('invalid source edit position')
        if target is not None and not _integer(target):
            raise ValueError('invalid source edit target')
        return EditBinding(sequence, operation, before, after, position, target)
    if kind == 'window' and len(raw) == 5:
        _, sequence, window_id, state_id, digest = raw
        if not _integer(sequence) or sequence < 1:
            raise ValueError('source window sequence must be a positive integer')
        if not is_identifier(window_id) or not is_identifier(state_id) or not _digest_hex(digest):
            raise ValueError('invalid source window binding')
        return WindowBinding(sequence, window_id, state_id, digest)
    raise ValueError('unknown source event shape')


def decode_material(raw: bytes) -> SourceMaterial:
    if type(raw) is not bytes:
        raise ValueError('source material must be bytes')
    data = load_json(raw)
    fields = {'recording_id', 'attempt_id', 'start', 'final_state', 'events'}
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError('invalid source material fields')
    recording_id = data['recording_id']
    attempt_id = data['attempt_id']
    final_state = data['final_state']
    if not is_identifier(recording_id) or not is_identifier(attempt_id) or not is_identifier(final_state):
        raise ValueError('invalid source material identifiers')
    start_data = data['start']
    if not isinstance(start_data, dict) or start_data.keys() != {'state_id', 'row_count'}:
        raise ValueError('invalid source material start')
    if not is_identifier(start_data['state_id']) or not _integer(start_data['row_count']) \
            or start_data['row_count'] < 0:
        raise ValueError('invalid source material start')
    if not isinstance(data['events'], list):
        raise ValueError('source events must be an array')
    events = tuple(_source_event(item) for item in data['events'])
    sequences = [event.sequence for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError('source events must be numbered from one without gaps')
    return SourceMaterial(recording_id, attempt_id,
                          ShiftStart(start_data['state_id'], start_data['row_count']),
                          final_state, events)


def _proof_data(proofs: tuple[tuple[int, str], ...]) -> list[list[object]]:
    return [[sequence, tag] for sequence, tag in proofs]


def encode_cert_payload(payload: CertPayload) -> bytes:
    return json_bytes({
        'recording_id': payload.recording_id,
        'start': _start_data(payload.material),
        'attempt_id': payload.attempt_id,
        'records': [{'attempt_id': record.attempt_id,
                     'source_sequence': record.source_sequence,
                     'record': encode_record(record.entry),
                     'source_evidence': record.source_evidence}
                    for record in payload.records],
        'source_proof': {'material': base64.b64encode(encode_material(payload.material)).decode('ascii'),
                         'proofs': _proof_data(payload.proofs),
                         'end_proof': payload.end_proof},
    })


def _read_proofs(raw: object) -> tuple[tuple[int, str], ...]:
    if not isinstance(raw, list):
        raise ValueError('source proofs must be an array')
    proofs = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('source proof requires a sequence and a tag')
        sequence, tag = item
        if not _integer(sequence) or sequence < 1:
            raise ValueError('source proof sequence must be a positive integer')
        if not is_identifier(tag):
            raise ValueError('source proof tag must be non-empty text')
        proofs.append((sequence, tag))
    sequences = [sequence for sequence, _ in proofs]
    if sequences != list(range(1, len(proofs) + 1)):
        raise ValueError('source proofs must cover every event in order')
    return tuple(proofs)


def decode_cert_payload(raw: bytes) -> CertPayload:
    data = load_json(raw)
    fields = {'recording_id', 'start', 'attempt_id', 'records', 'source_proof'}
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError('invalid certified payload fields')
    recording_id = data['recording_id']
    attempt_id = data['attempt_id']
    if not is_identifier(recording_id) or not is_identifier(attempt_id):
        raise ValueError('invalid certified payload identifiers')
    start_data = data['start']
    if not isinstance(start_data, dict) or start_data.keys() != {'state_id', 'row_count'}:
        raise ValueError('invalid certified payload start')
    start = ShiftStart(start_data['state_id'], start_data['row_count'])
    if not isinstance(data['records'], list):
        raise ValueError('certified records must be an array')
    records = []
    for raw_record in data['records']:
        if not isinstance(raw_record, dict) or \
                raw_record.keys() != {'attempt_id', 'source_sequence', 'record', 'source_evidence'}:
            raise ValueError('invalid certified record fields')
        record_attempt = raw_record['attempt_id']
        sequence = raw_record['source_sequence']
        evidence = raw_record['source_evidence']
        if record_attempt != attempt_id:
            raise ValueError('certified record attempt differs from the payload')
        if not _integer(sequence) or sequence < 1:
            raise ValueError('certified record sequence must be a positive integer')
        if not is_identifier(evidence):
            raise ValueError('certified record requires source evidence')
        records.append(CertRecord(record_attempt, sequence, decode_record(raw_record['record']), evidence))
    sequences = [record.source_sequence for record in records]
    if sequences != sorted(set(sequences)):
        raise ValueError('certified records must be unique and in source order')
    proof_data = data['source_proof']
    if not isinstance(proof_data, dict) or proof_data.keys() != {'material', 'proofs', 'end_proof'}:
        raise ValueError('invalid source proof fields')
    encoded = proof_data['material']
    if not isinstance(encoded, str):
        raise ValueError('source material must be encoded text')
    try:
        material_raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('source material is not valid encoded bytes') from exc
    material = decode_material(material_raw)
    proofs = _read_proofs(proof_data['proofs'])
    end_proof = proof_data['end_proof']
    if not isinstance(end_proof, str):
        raise ValueError('source proof end tag must be text')
    return CertPayload(recording_id, start, attempt_id, tuple(records), material, proofs, end_proof)


def validate_material_chain(material: SourceMaterial) -> None:
    """Ensure the material itself describes a complete, reachable shift."""
    current = material.start.state_id
    counts = {current: material.start.row_count}
    for event in material.events:
        if isinstance(event, EditBinding):
            if event.before != current:
                raise ValueError('source edit does not continue the material state')
            if event.after in counts:
                raise ValueError('source material reuses a table state')
            counts[event.after] = edit_row_count(
                EditFact(event.kind, event.before, event.after, event.position, event.target),
                counts[current])
            current = event.after
        elif event.state_id not in counts:
            raise ValueError('source window refers to an unknown table state')
    if current != material.final_state:
        raise ValueError('source material end state does not match its edits')


def verify_material(payload: CertPayload, expected_recording_id: str,
                    expected_attempt_id: str, verify_source) -> SourceMaterial:
    """Verify the delivered certified payload against independent expectations."""
    material = payload.material
    if payload.recording_id != expected_recording_id:
        raise ValueError('recording identity differs from the archive expectation')
    if material.recording_id != payload.recording_id:
        raise ValueError('source material recording differs from the bundle')
    if payload.attempt_id != expected_attempt_id:
        raise ValueError('attempt identity differs from the archive expectation')
    if material.attempt_id != payload.attempt_id:
        raise ValueError('source material attempt differs from the bundle')
    if material.start != payload.start:
        raise ValueError('source material start differs from the bundle')
    validate_material_chain(material)

    if tuple(sequence for sequence, _ in payload.proofs) != \
            tuple(event.sequence for event in material.events):
        raise ValueError('source proofs do not cover the delivered material')
    proof_map = dict(payload.proofs)
    for position, event in enumerate(material.events, start=1):
        if not verify_source(event_message(material, position), proof_map[event.sequence]):
            raise ValueError(f'source event {event.sequence} is not authenticated')
    if not verify_source(end_message(material), payload.end_proof):
        raise ValueError('source end is not authenticated')

    by_sequence = {event.sequence: event for event in material.events}
    delivered_edits = []
    seen = set()
    for record in payload.records:
        event = by_sequence.get(record.source_sequence)
        if event is None:
            raise ValueError(f'delivered record {record.source_sequence} has no source binding')
        if record.source_sequence in seen:
            raise ValueError('delivered source sequence is repeated')
        seen.add(record.source_sequence)
        if record.source_evidence != proof_map[record.source_sequence]:
            raise ValueError(f'delivered record {record.source_sequence} carries foreign evidence')
        if isinstance(event, EditBinding):
            if not isinstance(record.entry, EditFact):
                raise ValueError('source edit binding does not match the delivered record')
            expected = EditFact(event.kind, event.before, event.after, event.position, event.target)
            if record.entry != expected:
                raise ValueError(f'delivered edit {record.source_sequence} differs from the source material')
            delivered_edits.append(event.sequence)
        else:
            if not isinstance(record.entry, CapturedWindow):
                raise ValueError('source window binding does not match the delivered record')
            if record.entry.window_id != event.window_id or record.entry.state_id != event.state_id:
                raise ValueError(f'delivered window {record.source_sequence} has a foreign binding')
            if window_digest(record.entry) != event.digest:
                raise ValueError(f'delivered window {record.source_sequence} content differs from its binding')

    expected_edits = [event.sequence for event in material.events if isinstance(event, EditBinding)]
    if delivered_edits != expected_edits:
        raise ValueError('delivered records do not carry every edit fact')
    return material


def material_record(material: SourceMaterial, proofs: tuple[tuple[int, str], ...],
                    end_proof: str) -> dict[str, object]:
    """JSON-safe archive form of the verification material."""
    return {
        'recording_id': material.recording_id,
        'attempt_id': material.attempt_id,
        'start': _start_data(material),
        'final_state': material.final_state,
        'events': [_event_data(event) for event in material.events],
        'proofs': _proof_data(proofs),
        'end_proof': end_proof,
    }
