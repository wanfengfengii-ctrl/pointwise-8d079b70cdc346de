import sqlite3
from dataclasses import dataclass
from pathlib import Path

from archive.publish import PublishFailed, publish_draft
from archive.schema import DraftLine, SignedDraft
from bundle.catalog import load_received
from bundle.intake import verify_bundle
from bundle.source import CertPayload, material_record, verify_material
from review.coverage import EvidenceConflict, compute_coverage
from review.eligibility import qualify_observation
from review.history import InvalidHistory, validate_entries, validate_history
from review.origin import build_origin_map


@dataclass(frozen=True, slots=True)
class MissingOrigins:
    received_no: int
    positions: tuple[int, ...]


class ReconcileRejected(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f'{code}: {detail}')


def _coverage(payload, history, received_no):
    origins = build_origin_map(history)
    eligible = (qualify_observation(origins, sequence, window, row)
                for sequence, window in history.windows for row in window.rows)
    try:
        coverage = compute_coverage(history.start.row_count,
                                    (item for item in eligible if item is not None))
    except EvidenceConflict as exc:
        raise ReconcileRejected('evidence_conflict', str(exc)) from exc
    if coverage.missing:
        return MissingOrigins(received_no, coverage.missing)
    return coverage


def _sign(archive_path, received_no, recording_id, coverage, source_proof):
    lines = tuple(DraftLine(item.origin_position, item.mm, item.state_id, item.window_id,
                            item.screen_position, item.capture_sequence)
                  for item in coverage.covered)
    try:
        return publish_draft(archive_path, received_no, recording_id, lines,
                             source_proof=source_proof)
    except PublishFailed as exc:
        raise ReconcileRejected('publish_failed', str(exc)) from exc


def _certified(payload: CertPayload, catalog_path, archive_path, received_no,
               expected_recording_id, expected_attempt_id, verify_source):
    if not (isinstance(expected_recording_id, str) and isinstance(expected_attempt_id, str)
            and callable(verify_source)):
        raise ReconcileRejected('source_verifier_required',
                                'certified bundles require an expected recording, attempt and verifier')
    try:
        material = verify_material(payload, expected_recording_id, expected_attempt_id,
                                   verify_source)
    except (ValueError, TypeError) as exc:
        raise ReconcileRejected('source_unverified', str(exc)) from exc
    try:
        history = validate_entries(payload.start,
                                   ((record.source_sequence, record.entry)
                                    for record in payload.records))
    except InvalidHistory as exc:
        raise ReconcileRejected('invalid_history', str(exc)) from exc
    coverage = _coverage(payload, history, received_no)
    if isinstance(coverage, MissingOrigins):
        return coverage
    proof = {'attempt_id': payload.attempt_id,
             'material': material_record(material, payload.proofs, payload.end_proof)}
    return _sign(archive_path, received_no, payload.recording_id, coverage, proof)


def reconcile_bundle(catalog_path: str | Path, archive_path: str | Path,
                     received_no: int, *, expected_recording_id: str | None = None,
                     expected_attempt_id: str | None = None,
                     verify_source=None) -> SignedDraft | MissingOrigins:
    certified_mode = any(value is not None for value in
                         (expected_recording_id, expected_attempt_id, verify_source))
    try:
        received = load_received(catalog_path, received_no)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise ReconcileRejected('receipt_unavailable', str(exc)) from exc
    if received is None:
        raise ReconcileRejected('unknown_receipt', f'received number {received_no!r} is unavailable')

    try:
        payload = verify_bundle(received.raw)
        if payload.recording_id != received.recording_id:
            raise ValueError('recorded intake identity differs from fixed content')
    except ValueError as exc:
        raise ReconcileRejected('invalid_bundle', str(exc)) from exc

    if isinstance(payload, CertPayload):
        return _certified(payload, catalog_path, archive_path, received_no,
                          expected_recording_id, expected_attempt_id, verify_source)
    if certified_mode:
        raise ReconcileRejected('uncertified_bundle',
                                'a V1 bundle carries no source proof to verify')

    try:
        history = validate_history(payload)
    except InvalidHistory as exc:
        raise ReconcileRejected('invalid_history', str(exc)) from exc
    coverage = _coverage(payload, history, received_no)
    if isinstance(coverage, MissingOrigins):
        return coverage
    return _sign(archive_path, received_no, payload.recording_id, coverage, None)
