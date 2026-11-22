import sqlite3
from pathlib import Path

from archive.schema import DraftLine, FirstReceipt, SignedDraft
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


def publish_draft(path: str | Path, received_no: int, recording_id: str,
                  lines: tuple[DraftLine, ...]) -> SignedDraft:
    try:
        if not valid_number(received_no) or not is_identifier(recording_id):
            raise ValueError('draft requires an exact received number and recording identifier')
        lines = _verified_lines(lines)
        with open_store(path) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            result = insert_result_header(connection, received_no, recording_id)
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
    return SignedDraft(result.result_no, received_no, recording_id, lines, receipt)
