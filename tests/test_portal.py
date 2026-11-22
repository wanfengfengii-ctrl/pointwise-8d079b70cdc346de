import unittest

from portal.edits import AppliedEdit, RecordedEdit
from portal.recording import (RecordedRead, RecordedReadAt, RecordingCatalog, ShiftRecording,
                              load_recordings)
from portal.replay import open_shift
from portal.windows import WindowRead
from tests.support import RECORDINGS


class PortalTests(unittest.TestCase):
    def test_unknown_recording(self):
        with self.assertRaisesRegex(KeyError, 'unknown recording'):
            open_shift(load_recordings(RECORDINGS), 'unknown')

    def test_actual_read_after_move(self):
        catalog = load_recordings(RECORDINGS)
        state, count, replay = open_shift(catalog, 'scroll-missing')
        _, _, independent = open_shift(catalog, 'scroll-missing')
        self.assertEqual((state, count), ('s0', 4))
        self.assertEqual(replay.next_event(), WindowRead('start', 's0', ((1, 7), (2, 11))))
        self.assertEqual(replay.next_event(), AppliedEdit('move', 's0', 's1', 4, 1))
        self.assertEqual(replay.next_event(), WindowRead('shifted', 's1', ((1, 13), (2, 7))))
        self.assertEqual(independent.snapshot.rows, (7, 11, 7, 13))
        self.assertEqual(independent.next_event(), WindowRead('start', 's0', ((1, 7), (2, 11))))

    def test_edit_kinds(self):
        steps = (RecordedEdit('insert', 'a', 'b', 3, mm=9),
                 RecordedEdit('move', 'b', 'c', 1, target=3),
                 RecordedEdit('delete', 'c', 'd', 2),
                 RecordedEdit('rewrite', 'd', 'e', 2, mm=0))
        catalog = RecordingCatalog([ShiftRecording('edits', 'a', (0, 4), steps)])
        _, _, replay = open_shift(catalog, 'edits')
        for fact, table in (
            (AppliedEdit('insert', 'a', 'b', 3), (0, 4, 9)),
            (AppliedEdit('move', 'b', 'c', 1, 3), (4, 9, 0)),
            (AppliedEdit('delete', 'c', 'd', 2), (4, 0)),
            (AppliedEdit('rewrite', 'd', 'e', 2), (4, 0)),
        ):
            self.assertEqual(replay.next_event(), fact)
            self.assertEqual((replay.snapshot.state_id, replay.snapshot.rows), (fact.after, table))
        self.assertIsNone(replay.next_event())

    def test_invalid_portal_steps_leave_snapshot(self):
        invalid_sequences = (
            (RecordedEdit('delete', 'wrong', 'b', 1),),
            (RecordedEdit('move', 'a', 'b', 1, target=2),),
            (RecordedEdit('rewrite', 'a', 'b', 1, mm=True),),
            (RecordedRead('out', 2, 1), RecordedReadAt('out')),
            (RecordedReadAt('unscheduled'),),
            (RecordedRead('pending', 1, 1),),
        )
        for steps in invalid_sequences:
            with self.subTest(steps=steps):
                catalog = RecordingCatalog([ShiftRecording('bad', 'a', (0,), steps)])
                _, _, replay = open_shift(catalog, 'bad')
                before = replay.snapshot
                with self.assertRaises(ValueError):
                    replay.next_event()
                self.assertEqual(replay.snapshot, before)
