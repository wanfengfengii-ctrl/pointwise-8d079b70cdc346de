from dataclasses import replace

from archive.readback import UnavailableResult, read
from bundle.issue import seal
from capture.session import capture_window, finish_capture, start_capture
from portal.edits import AppliedEdit, RecordedEdit
from portal.recording import RecordingCatalog
from portal.replay import open_shift
from review.decision import ReconcileRejected
from storage import open_store
from tests.support import ProjectTest, SCROLL_LINES, lines_of, scenario


class ArchiveTests(ProjectTest):
    def test_failed_publish(self):
        prior = self.decide(self.receive(self.raw('stable')))
        before = self.archive_counts()
        self.assertEqual(before, (1, 3, 1))
        with open_store(self.workspace.archive) as connection, connection:
            connection.execute('''CREATE TRIGGER block_first_receipt BEFORE INSERT ON first_receipts
                                  BEGIN SELECT RAISE(ABORT, 'first receipt write failed'); END''')
        new_number = self.receive(self.raw('scroll-complete'))
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide(new_number)
        self.assertEqual(caught.exception.code, 'publish_failed')
        self.assertIn('first receipt write failed', str(caught.exception))
        self.assertEqual(self.archive_counts(), before)
        with self.assertRaises(UnavailableResult):
            read(self.workspace.archive, prior.result_no + 1)
        self.assertEqual(read(self.workspace.archive, prior.result_no), prior)
        scenario('v7', {'existing_result': prior.result_no, 'write_failure': 'first_receipts insert'},
                 'publish_failed', caught.exception.code, [1, 3, 1], list(self.archive_counts()),
                 ['archive/shift_index.py', 'archive/publish.py', 'archive/readback.py'],
                 'The existing stable draft has exactly one header, three lines and one receipt.')
        with open_store(self.workspace.archive) as connection, connection:
            connection.execute('DROP TRIGGER block_first_receipt')
        signed = self.decide(new_number)
        self.assertEqual(lines_of(signed), SCROLL_LINES)
        self.assertEqual(signed.receipt.received_no, new_number)
        self.assertEqual(self.archive_counts(), (2, 7, 2))

    def test_read_after_reopen(self):
        recording = self.recordings.lookup('scroll-complete')
        continued = replace(recording, steps=recording.steps + (RecordedEdit('delete', 's2', 's3', 1),))
        catalog = RecordingCatalog((continued,))
        state, count, portal = open_shift(catalog, continued.recording_id)
        session = start_capture(continued.recording_id, state, count)
        for _ in range(6):
            capture_window(session, portal.next_event())
        self.assertEqual(portal.snapshot.rows, (13, 7, 11, 19))
        finish_capture(session)
        signed = self.decide(self.receive(seal(session)))
        self.assertEqual(lines_of(signed), SCROLL_LINES)
        self.assertEqual(portal.next_event(), AppliedEdit('delete', 's2', 's3', 1))
        self.assertEqual(portal.snapshot.rows, (7, 11, 19))
        del portal, session, catalog
        self.workspace.recordings.unlink()
        reopened = read(self.workspace.archive, signed.result_no)
        self.assertEqual(reopened, signed)
        self.assertEqual(lines_of(reopened), SCROLL_LINES)
        self.assertEqual(reopened.lines[2].screen_position, 4)
        self.assertEqual(reopened.lines[3].screen_position, 1)
        scenario('v8', {'recording_id': 'scroll-complete', 'post_sign_delete': 1},
                 SCROLL_LINES, lines_of(signed), SCROLL_LINES, lines_of(reopened),
                 ['portal/replay.py', 'archive/publish.py', 'archive/readback.py'],
                 'Original rows 3 and 4 use the moved-state positions 4 and 1. The later deletion follows signing.')

    def test_unknown_result(self):
        self.decide(self.receive(self.raw('stable')))
        for number in (0, 2, 1 << 70, True):
            with self.subTest(number=number):
                with self.assertRaises(UnavailableResult):
                    read(self.workspace.archive, number)
