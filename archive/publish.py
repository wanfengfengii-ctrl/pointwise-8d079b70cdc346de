import json
import sqlite3
from pathlib import Path

from archive.schema import CertifiedDraft, DraftLine, FirstReceipt, SignedDraft
from archive.shift_index import insert_result_header
from portal.table import is_identifier
from storage import open_store, valid_number


class PublishFailed(ValueError):
    pass


def _verified_lines(lines: tuple[DraftLine, ...]) -> tuple[DraftLine, ...]:
    verified = tuple(lines)
    for position, line in enumerate(verified, start=1):
        if not isinstance(line, DraftLine) or type(line.origin_position) is not int or line.origin_position != position:
            raise ValueError('draft lines must cover consecutive origin positions in order')
        if type(line.mm) is not int:
            raise ValueError('draft reading must be integer millimetres')
        if not is_identifier(line.state_id) or not is_identifier(line.window_id):
            raise ValueError('invalid draft evidence identifiers')
        if not valid_number(line.screen_position) or not valid_number(line.capture_sequence):
            raise ValueError('invalid draft evidence location')
    return verified


def _proof_text(source_proof: dict | None) -> str | None:
    if source_proof is None:
        return None
    if not isinstance(source_proof, dict) or not is_identifier(source_proof.get('attempt_id')) \
            or not isinstance(source_proof.get('material'), dict):
        raise ValueError('source proof requires an attempt and verification material')
    return json.dumps(source_proof, sort_keys=True, separators=(',', ':'), allow_nan=False)


def publish_draft(path: str | Path, received_no: int, recording_id: str,
                  lines: tuple[DraftLine, ...], *, source_proof: dict | None = None) -> SignedDraft:
    try:
        if not valid_number(received_no) or not is_identifier(recording_id):
            raise ValueError('draft requires an exact received number and recording identifier')
        lines = _verified_lines(lines)
        proof_text = _proof_text(source_proof)
        with open_store(path) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            result = insert_result_header(connection, received_no, recording_id, proof_text)
            connection.executemany(
                '''INSERT INTO draft_lines (result_no, origin_position, mm_decimal, state_id,
                       window_id, screen_position, capture_sequence) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                ((result.result_no, line.origin_position, str(line.mm), line.state_id,
                  line.window_id, line.screen_position, line.capture_sequence) for line in lines),
            )
            cursor = connection.execute('INSERT INTO first_receipts (result_no) VALUES (?)', (result.result_no,))
            receipt = FirstReceipt(cursor.lastrowid, result.result_no, received_no)
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        raise PublishFailed(str(exc)) from exc
    if source_proof is None:
        return SignedDraft(result.result_no, received_no, recording_id, lines, receipt)
    return CertifiedDraft(result.result_no, received_no, recording_id, lines, receipt, source_proof)
