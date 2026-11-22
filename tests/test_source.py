import json
from dataclasses import replace

from archive.readback import read
from archive.schema import SignedDraft
from bundle.envelope import verify_envelope, wrap_payload
from bundle.source import decode_cert_payload, encode_cert_payload
from capture.edit_log import EditFact
from capture.observations import CapturedWindow
from handoff import capture_recording as capture
from review.decision import MissingOrigins, ReconcileRejected
from source_fixture import EXAMPLE_KEY, auth_ports, replay_inputs
from tests.support import ProjectTest, scenario


RECORDING = 'scroll-complete'


class SourceHandoffTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.attest, self.verify = auth_ports(EXAMPLE_KEY)
        self.inputs = replay_inputs()

    def certified(self, attempt, chosen):
        return capture(self.inputs[attempt], RECORDING, attempt_id=attempt,
                       attest=self.attest, select_windows=lambda positions: chosen)

    def decide_certified(self, number, attempt='B'):
        return self.decide(number, expected_recording_id=RECORDING,
                           expected_attempt_id=attempt, verify_source=self.verify)

    def verify_certified(self, raw, attempt='B'):
        number = self.receive(raw)
        try:
            return number, self.decide_certified(number, attempt)
        except ReconcileRejected as exc:
            return number, exc

    def inner(self, raw):
        return decode_cert_payload(verify_envelope(raw).payload)

    def reframe(self, inner):
        return wrap_payload(inner.recording_id, encode_cert_payload(inner))

    def lines(self, draft):
        return [(line.mm, line.state_id, line.window_id, line.screen_position, line.capture_sequence)
                for line in draft.lines]

    def test_certified_signs_b(self):
        raw = self.certified('B', (1, 3, 4))
        number = self.receive(raw)
        signed = self.decide_certified(number)
        self.assertIsInstance(signed, SignedDraft)
        self.assertEqual([line.mm for line in signed.lines], [7, 11, 7, 13])
        self.assertEqual([line.capture_sequence for line in signed.lines], [1, 1, 4, 3])
        self.assertEqual(signed.lines[2].state_id, 's1')
        self.assertEqual(signed.lines[2].screen_position, 4)
        self.assertEqual(signed.source_proof['attempt_id'], 'B')
        self.assertIn('material', signed.source_proof)
        scenario('s1.certified_b', {'attempt': 'B', 'selected': [1, 3, 4]},
                 [7, 11, 7, 13], [line.mm for line in signed.lines],
                 [1, 1, 4, 3], [line.capture_sequence for line in signed.lines],
                 ['capture/certified.py', 'bundle/source.py', 'review/decision.py'],
                 'The clerk picks source windows 1, 3 and 4; edit events keep their source sequence.')

    def test_unselected_windows_are_absent(self):
        raw = self.certified('B', (1,))
        inner = self.inner(raw)
        carried = [record.entry for record in inner.records if isinstance(record.entry, CapturedWindow)]
        self.assertEqual([window.window_id for window in carried], ['start'])
        self.assertEqual([record.source_sequence for record in inner.records], [1, 2, 5])
        self.assertEqual(self.receive(raw), 1)
        result = self.decide_certified(1)
        self.assertEqual(result, MissingOrigins(1, (3, 4)))

    def test_empty_selection_keeps_edits_only(self):
        inner = self.inner(self.certified('B', ()))
        self.assertTrue(all(isinstance(record.entry, EditFact) for record in inner.records))
        self.assertEqual([record.source_sequence for record in inner.records], [2, 5])
        number = self.receive(self.reframe(inner))
        self.assertEqual(self.decide_certified(number), MissingOrigins(number, (1, 2, 3, 4)))

    def test_out_of_order_selection_keeps_source_sequence(self):
        raw = self.certified('A', (5, 2, 4))
        signed = self.decide_certified(self.receive(raw), attempt='A')
        self.assertIsInstance(signed, SignedDraft)
        self.assertEqual([line.mm for line in signed.lines], [7, 11, 7, 13])
        self.assertEqual([line.capture_sequence for line in signed.lines], [2, 2, 5, 4])

    def test_b_selected_pair_missing_original(self):
        number = self.receive(self.certified('B', (1, 3)))
        self.assertEqual(self.decide_certified(number), MissingOrigins(number, (3,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_missing_edit_is_rejected(self):
        inner = self.inner(self.certified('B', (1, 3, 4)))
        stripped = replace(inner, records=tuple(record for record in inner.records
                                                if record.source_sequence != 5))
        number, result = self.verify_certified(self.reframe(stripped))
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(result.code, 'source_unverified')
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_missing_end_proof_is_rejected(self):
        inner = replace(self.inner(self.certified('B', (1, 3, 4))), end_proof='')
        number, result = self.verify_certified(self.reframe(inner))
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_rewritten_edit_position_is_rejected(self):
        inner = self.inner(self.certified('B', (1, 3, 4)))
        records = tuple(replace(record, entry=replace(record.entry, position=3))
                        if isinstance(record.entry, EditFact) else record for record in inner.records)
        number, result = self.verify_certified(self.reframe(replace(inner, records=records)))
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(result.code, 'source_unverified')

    def test_foreign_window_binding_is_rejected(self):
        inner_b = self.inner(self.certified('B', (1, 3, 4)))
        inner_a = self.inner(self.certified('A', (1, 2, 4, 5)))
        foreign = next(record for record in inner_a.records if record.source_sequence == 1)
        swapped = replace(inner_b, records=tuple(
            replace(foreign, attempt_id='B') if record.source_sequence == 1 else record
            for record in inner_b.records))
        number, result = self.verify_certified(self.reframe(swapped))
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(result.code, 'source_unverified')

    def test_tampered_window_body_is_rejected(self):
        inner = self.inner(self.certified('B', (1, 3, 4)))
        records = []
        for record in inner.records:
            if isinstance(record.entry, CapturedWindow):
                body = CapturedWindow(record.entry.window_id, record.entry.state_id,
                                      (replace(record.entry.rows[0], mm=99),) + record.entry.rows[1:])
                record = replace(record, entry=body)
            records.append(record)
        number, result = self.verify_certified(self.reframe(replace(inner, records=tuple(records))))
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(result.code, 'source_unverified')

    def test_wrong_attempt_is_rejected(self):
        raw = self.certified('A', (1, 2, 4, 5))
        number, result = self.verify_certified(raw, attempt='B')
        self.assertIsInstance(result, ReconcileRejected)
        self.assertEqual(result.code, 'source_unverified')
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_v1_bundle_rejected_in_certified_mode(self):
        number = self.receive(self.raw(RECORDING))
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide_certified(number)
        self.assertEqual(caught.exception.code, 'uncertified_bundle')
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        self.assertEqual(self.decide(number).__class__, SignedDraft)

    def test_missing_verifier_is_rejected(self):
        number = self.receive(self.certified('B', (1, 3, 4)))
        with self.assertRaises(ReconcileRejected):
            self.decide(number)

    def test_invalid_selection_rejected(self):
        for chosen in ((1, 1), (2,), (0,), (999,), (True,)):
            with self.subTest(chosen=chosen):
                with self.assertRaises(ValueError):
                    self.certified('B', chosen)

    def test_signed_proof_survives_portal_stop(self):
        signed = self.decide_certified(self.receive(self.certified('B', (1, 3, 4))))
        self.workspace.recordings.unlink()
        reopened = read(self.workspace.archive, signed.result_no)
        self.assertEqual(reopened, signed)
        self.assertEqual(reopened.source_proof, signed.source_proof)
        self.assertEqual(json.loads(json.dumps(reopened.source_proof)), signed.source_proof)
        self.assertEqual(reopened.source_proof['attempt_id'], 'B')
        self.assertIn('events', reopened.source_proof['material'])

    def test_b_failure_before_selection_leaves_no_bundle(self):
        calls = []
        state, count, portal = __import__('portal.replay', fromlist=['open_shift']).open_shift(
            self.inputs['B'], RECORDING)
        # A selector that raises must abort capture, and nothing is sealed.
        with self.assertRaises(RuntimeError):
            capture(self.inputs['B'], RECORDING, attempt_id='B', attest=self.attest,
                    select_windows=lambda positions: (_ for _ in ()).throw(RuntimeError('clerk left')))
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        self.assertEqual(self.intake_count(), 0)
        # Legacy capture stays two-argument and identical.
        self.assertEqual(self.raw(RECORDING), self.raw(RECORDING))

    def test_legacy_archive_migrates_and_keeps_result(self):
        from archive.schema import _AUX_TABLES
        from handoff import initialize_workspace
        from storage import open_store

        legacy = '''CREATE TABLE drafts (
        result_no INTEGER PRIMARY KEY,
        received_no INTEGER NOT NULL CHECK (received_no > 0),
        recording_id TEXT NOT NULL
    )'''
        archive = self.workspace.root / 'signed.sqlite3'
        archive.unlink()
        with open_store(archive, mode='rwc') as db, db:
            db.execute(legacy)
            db.execute(_AUX_TABLES['draft_lines'])
            db.execute(_AUX_TABLES['first_receipts'])
            db.execute("INSERT INTO drafts (received_no, recording_id) VALUES (7, 'stable')")
            db.execute("INSERT INTO draft_lines VALUES (1, 1, '0', 't0', 'top', 1, 1)")
            db.execute('INSERT INTO first_receipts (result_no) VALUES (1)')
        initialize_workspace(self.workspace.root)
        initialize_workspace(self.workspace.root)
        reopened = read(self.workspace.archive, 1)
        self.assertEqual([line.mm for line in reopened.lines], [0])
        self.assertIsNone(reopened.source_proof)
        certified = self.decide_certified(self.receive(self.certified('B', (1, 3, 4))))
        self.assertIsInstance(certified, SignedDraft)
        self.assertNotEqual(certified.result_no, 1)

