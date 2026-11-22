import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from bundle.envelope import wrap_payload
from bundle.format import BundlePayload, encode_payload
from bundle.intake import receive, verify_bundle
from capture.checkpoint import ShiftStart
from capture.observations import CapturedWindow, ObservedRow
from handoff import capture_recording, initialize_workspace
from portal.recording import load_recordings
from review.decision import reconcile_bundle
from storage import open_store


RECORDINGS = Path(__file__).resolve().parents[1] / 'data' / 'recordings.json'
SCROLL_LINES = [(1, 7, 's0', 'start', 1, 1), (2, 11, 's0', 'start', 2, 1),
                (3, 7, 's1', 'before-rewrite', 4, 4), (4, 13, 's1', 'shifted', 1, 3)]


def lines_of(draft):
    return [(line.origin_position, line.mm, line.state_id, line.window_id, line.screen_position,
             line.capture_sequence) for line in draft.lines]


def window(window_id, state_id, *pairs):
    return CapturedWindow(window_id, state_id, tuple(ObservedRow(*row) for row in pairs))


def pack(payload):
    return wrap_payload(payload.recording_id, encode_payload(payload))


def evidence(recording_id, state, row_count, *records):
    return BundlePayload(recording_id, ShiftStart(state, row_count), records)


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    event = dict(case_id=case_id, input=inputs, expected=expected, actual=actual,
                 downstream_expected=downstream_expected, downstream_actual=downstream_actual,
                 code_paths=code_paths, oracle=oracle)
    print('POINTWISE_SCENARIO ' + json.dumps(event, ensure_ascii=False, sort_keys=True), flush=True)


class ProjectTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix='test-harbour-handoff-')
        self.addCleanup(folder.cleanup)
        self.workspace = initialize_workspace(folder.name)
        self.recordings = load_recordings(self.workspace.recordings)

    def raw(self, recording_id):
        return capture_recording(self.recordings, recording_id)

    def payload(self, recording_id):
        return verify_bundle(self.raw(recording_id))

    def receive(self, raw):
        return receive(self.workspace.catalog, raw)

    def submit(self, payload):
        return self.receive(pack(payload))

    def decide(self, number):
        return reconcile_bundle(self.workspace.catalog, self.workspace.archive, number)

    def without_windows(self, recording_id, *window_ids):
        payload = self.payload(recording_id)
        records = tuple(entry for entry in payload.records
                        if not isinstance(entry, CapturedWindow) or entry.window_id not in window_ids)
        return replace(payload, records=records)

    def archive_counts(self):
        with open_store(self.workspace.archive, mode='ro') as db:
            headers = db.execute('SELECT count(*) FROM drafts').fetchone()[0]
            lines = db.execute('SELECT count(*) FROM draft_lines').fetchone()[0]
            receipts = db.execute('SELECT count(*) FROM first_receipts').fetchone()[0]
        return headers, lines, receipts

    def intake_count(self):
        with open_store(self.workspace.catalog, mode='ro') as db:
            return db.execute('SELECT count(*) FROM received_bundles').fetchone()[0]
