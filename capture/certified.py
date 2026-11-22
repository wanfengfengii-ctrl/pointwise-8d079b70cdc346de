"""Portal-side certified capture: replay, attest every source event, then select."""
from dataclasses import dataclass

from bundle.envelope import wrap_payload
from bundle.format import BundlePayload
from bundle.source import (CertPayload, CertRecord, SourceMaterial, WindowBinding, edit_binding,
                           encode_cert_payload, end_message, event_message, window_binding)
from capture.session import capture_window, finish_capture, start_capture
from portal.edits import AppliedEdit
from portal.replay import open_shift
from portal.table import is_identifier


class CertificationFailed(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CapturedShift:
    payload: BundlePayload
    material: SourceMaterial
    proofs: tuple[tuple[int, str], ...]
    end_proof: str


def _capture(recording_id: str, attempt_id: str, attest, portal) -> CapturedShift:
    """Drive the portal replay to its normal end, attesting every source event."""
    state, row_count, replay = portal
    session = start_capture(recording_id, state, row_count)
    material = SourceMaterial(recording_id, attempt_id, session.checkpoint.start, state, ())
    records = []
    proofs: list[tuple[int, str]] = []
    while (event := replay.next_event()) is not None:
        capture_window(session, event)
        entry = session.records[-1]
        sequence = len(records) + 1
        binding = edit_binding(sequence, entry) if isinstance(event, AppliedEdit) \
            else window_binding(sequence, entry)
        material = SourceMaterial(recording_id, attempt_id, material.start,
                                  state, material.events + (binding,))
        records.append(entry)
        proofs.append((sequence, attest(event_message(material, sequence))))
    finish_capture(session)
    material = SourceMaterial(recording_id, attempt_id, material.start,
                              session.checkpoint.current_state, material.events)
    end_proof = attest(end_message(material))
    return CapturedShift(BundlePayload(recording_id, material.start, tuple(records)),
                         material, tuple(proofs), end_proof)


def _window_sequences(material: SourceMaterial) -> tuple[int, ...]:
    return tuple(event.sequence for event in material.events if isinstance(event, WindowBinding))


def _chosen(chosen) -> tuple[int, ...]:
    try:
        values = tuple(chosen)
    except TypeError as exc:
        raise CertificationFailed('window selection is not iterable') from exc
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise CertificationFailed('selected window sequence must be a positive integer')
    if len(set(values)) != len(values):
        raise CertificationFailed('selected window sequences must be distinct')
    return values


def build_certified_payload(shift: CapturedShift, chosen) -> CertPayload:
    candidates = _chosen(chosen)
    windows = _window_sequences(shift.material)
    if any(sequence not in windows for sequence in candidates):
        raise CertificationFailed('selected source sequence is not an actual window')
    selected = set(candidates)
    odds = dict(shift.proofs)
    records = []
    for sequence, (entry, binding) in enumerate(zip(shift.payload.records, shift.material.events),
                                               start=1):
        if isinstance(binding, WindowBinding) and sequence not in selected:
            continue
        records.append(CertRecord(shift.material.attempt_id, sequence, entry, odds[sequence]))
    return CertPayload(shift.payload.recording_id, shift.material.start,
                       shift.material.attempt_id, tuple(records), shift.material,
                       shift.proofs, shift.end_proof)


def seal_certified(payload: CertPayload) -> bytes:
    if not is_identifier(payload.attempt_id) or payload.attempt_id != payload.material.attempt_id:
        raise CertificationFailed('certified material attempt differs from the bundle')
    inner = encode_cert_payload(payload)
    return wrap_payload(payload.recording_id, inner)


def certified_capture(catalog, recording_id: str, attempt_id: str, attest, select_windows) -> bytes:
    """Complete a certified capture and return the fixed bundle bytes."""
    if not is_identifier(recording_id) or not is_identifier(attempt_id):
        raise ValueError('certified capture requires a recording and attempt identifier')
    if not callable(attest) or not callable(select_windows):
        raise ValueError('certified capture requires portal callbacks')
    portal = open_shift(catalog, recording_id)
    shift = _capture(recording_id, attempt_id, attest, portal)
    payload = build_certified_payload(shift, select_windows(_window_sequences(shift.material)))
    return seal_certified(payload)
