import sqlite3
from dataclasses import dataclass
from pathlib import Path

from archive.publish import PublishFailed, publish_draft
from archive.schema import DraftLine, SignedDraft
from bundle.catalog import load_received
from bundle.intake import verify_bundle
from review.coverage import EvidenceConflict, compute_coverage
from review.eligibility import qualify_observation
from review.history import InvalidHistory, validate_history
from review.origin import build_origin_map


@dataclass(frozen=True, slots=True)
class MissingOrigins:
    received_no: int
    positions: tuple[int, ...]


class ReconcileRejected(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f'{code}: {detail}')


def reconcile_bundle(catalog_path: str | Path, archive_path: str | Path,
                     received_no: int) -> SignedDraft | MissingOrigins:
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

    try:
        history = validate_history(payload)
    except InvalidHistory as exc:
        raise ReconcileRejected('invalid_history', str(exc)) from exc
    origins = build_origin_map(history)
    eligible = (qualify_observation(origins, sequence, window, row)
                for sequence, window in history.windows for row in window.rows)
    try:
        coverage = compute_coverage(history.start.row_count, (item for item in eligible if item is not None))
    except EvidenceConflict as exc:
        raise ReconcileRejected('evidence_conflict', str(exc)) from exc
    if coverage.missing:
        return MissingOrigins(received_no, coverage.missing)

    lines = tuple(DraftLine(item.origin_position, item.mm, item.state_id, item.window_id,
                            item.screen_position, item.capture_sequence) for item in coverage.covered)
    try:
        return publish_draft(archive_path, received_no, payload.recording_id, lines)
    except PublishFailed as exc:
        raise ReconcileRejected('publish_failed', str(exc)) from exc
