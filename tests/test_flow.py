import json
from dataclasses import asdict

from archive.readback import read
from bundle.catalog import load_received
from handoff import initialize_workspace
from portal.recording import load_recordings
from review.decision import MissingOrigins, ReconcileRejected
from storage import IncompatibleStore, open_store
from tests.support import ProjectTest, SCROLL_LINES, evidence, lines_of, pack, window


class FlowTests(ProjectTest):
    def test_exact_receipt(self):
        raw_a = self.raw('scroll-complete')
        raw_b = pack(self.without_windows('scroll-complete', 'before-rewrite'))
        first, second = self.receive(raw_a), self.receive(raw_b)
        self.assertNotEqual(first, second)
        self.workspace.recordings.unlink()
        self.assertEqual(load_received(self.workspace.catalog, first).raw, raw_a)
        self.assertEqual(load_received(self.workspace.catalog, second).raw, raw_b)
        self.assertEqual(self.decide(second), MissingOrigins(second, (3,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        signed = self.decide(first)
        self.assertEqual(signed.recording_id, 'scroll-complete')
        self.assertEqual(signed.received_no, first)
        self.assertEqual(lines_of(signed), SCROLL_LINES)
        self.assertEqual(read(self.workspace.archive, signed.result_no).receipt.received_no, first)
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide(second + 1)
        self.assertEqual(caught.exception.code, 'unknown_receipt')

    def test_repeat_init(self):
        raw = self.raw('stable')
        number = self.receive(raw)
        signed = self.decide(number)
        source = json.loads(self.workspace.recordings.read_bytes())
        source['recordings'][0]['initial_rows'][0] = 42
        edited = json.dumps(source, indent=2).encode()
        self.workspace.recordings.write_bytes(edited)
        workspace = initialize_workspace(self.workspace.root)
        self.assertEqual(workspace.recordings.read_bytes(), edited)
        self.assertEqual(load_recordings(workspace.recordings).lookup('stable').initial_rows, (42, 12, 5))
        self.assertEqual(load_received(workspace.catalog, number).raw, raw)
        self.assertEqual(read(workspace.archive, signed.result_no), signed)
        self.assertEqual(self.archive_counts(), (1, 3, 1))

    def test_init_fills_missing_tables_and_refuses_incompatible_data(self):
        with open_store(self.workspace.archive) as db, db:
            db.execute('DROP TABLE draft_lines')
        initialize_workspace(self.workspace.root)
        signed = self.decide(self.receive(self.raw('stable')))
        with open_store(self.workspace.catalog) as db, db:
            db.execute('ALTER TABLE received_bundles ADD COLUMN operator_note TEXT')
            db.execute('UPDATE received_bundles SET operator_note = ?', ('keep this',))
        with self.assertRaisesRegex(IncompatibleStore, 'received_bundles'):
            initialize_workspace(self.workspace.root)
        with open_store(self.workspace.catalog, mode='ro') as db:
            self.assertEqual(db.execute('SELECT operator_note FROM received_bundles').fetchall(), [('keep this',)])
        self.assertEqual(read(self.workspace.archive, signed.result_no), signed)

    def test_zero_origin_rows(self):
        number = self.submit(evidence('empty', 'a', 0))
        signed = self.decide(number)
        self.assertEqual(signed.lines, ())
        self.assertEqual(self.archive_counts(), (1, 0, 1))
        self.assertEqual(read(self.workspace.archive, signed.result_no), signed)
        self.assertEqual(signed.receipt.received_no, number)

    def test_integer_precision_through_storage(self):
        large = (1 << 100) + 23
        number = self.submit(evidence('precision', 'a', 2, window('wide', 'a', (1, large), (2, -large))))
        signed = self.decide(number)
        reopened = read(self.workspace.archive, signed.result_no)
        self.assertEqual([line.mm for line in reopened.lines], [large, -large])
        self.assertEqual(asdict(reopened)['lines'][0]['mm'], large)
