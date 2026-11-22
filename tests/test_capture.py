import unittest

from bundle.intake import verify_bundle
from bundle.issue import seal
from capture.checkpoint import ShiftStart
from capture.edit_log import EditFact
from capture.observations import CapturedWindow
from capture.session import capture_window, finish_capture, start_capture
from handoff import capture_recording
from portal.edits import AppliedEdit
from portal.recording import load_recordings
from portal.windows import WindowRead
from tests.support import RECORDINGS, scenario, window


class CaptureTests(unittest.TestCase):
    def test_stable_shift(self):
        catalog = load_recordings(RECORDINGS)
        raw = capture_recording(catalog, 'stable')
        payload = verify_bundle(raw)
        self.assertEqual(raw, capture_recording(catalog, 'stable'))
        self.assertEqual(payload.start, ShiftStart('t0', 3))
        self.assertEqual(payload.records, (window('top', 't0', (1, 0), (2, 12)),
                                           window('bottom', 't0', (3, 5))))
        readings = [row.mm for entry in payload.records for row in entry.rows]
        sources = [[entry.window_id, row.position] for entry in payload.records for row in entry.rows]
        scenario('v1', {'recording_id': 'stable', 'start_mm': [0, 12, 5]}, [0, 12, 5], readings,
                 [['top', 1], ['top', 2], ['bottom', 3]], sources,
                 ['portal/replay.py', 'capture/session.py', 'bundle/issue.py'],
                 'The first window covers positions 1 and 2, and the second covers position 3.')

    def test_overlap_after_move(self):
        raw = capture_recording(load_recordings(RECORDINGS), 'scroll-missing')
        payload = verify_bundle(raw)
        self.assertEqual(payload.records, (
            window('start', 's0', (1, 7), (2, 11)), EditFact('move', 's0', 's1', 4, 1),
            window('shifted', 's1', (1, 13), (2, 7)), EditFact('rewrite', 's1', 's2', 4),
            window('after-rewrite', 's2', (3, 11), (4, 19)),
        ))
        observed = [[entry.window_id, entry.state_id, [[r.position, r.mm] for r in entry.rows]]
                    for entry in payload.records if isinstance(entry, CapturedWindow)]
        expected = [['start', 's0', [[1, 7], [2, 11]]], ['shifted', 's1', [[1, 13], [2, 7]]],
                    ['after-rewrite', 's2', [[3, 11], [4, 19]]]]
        scenario('v2', {'start_mm': [7, 11, 7, 13], 'move': [4, 1], 'rewrite': [4, 19]},
                 expected[:2], observed[:2], expected, observed,
                 ['portal/replay.py', 'capture/timeline.py', 'bundle/format.py'],
                 'Moving the last row to the front changes the first two readings to 13 and 7.')

    def test_invalid_event_atomic(self):
        session = start_capture('atomic', 'a', 2)
        capture_window(session, WindowRead('first', 'a', ((1, 0),)))
        capture_window(session, AppliedEdit('move', 'a', 'b', 2, 1))
        checkpoint, records = session.checkpoint, session.records
        for event in (
            WindowRead('unknown', 'c', ((1, 2),)),
            WindowRead('bad-position', 'b', ((3, 2),)),
            WindowRead('bool', 'b', ((2, True),)),
            WindowRead('null', 'b', ((2, None),)),
            WindowRead('duplicate', 'b', ((1, 2), (1, 2))),
            AppliedEdit('delete', 'a', 'c', 1),
            AppliedEdit('move', 'b', 'c', 1, 3),
            AppliedEdit('delete', 'b', 'a', 1),
        ):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    capture_window(session, event)
                self.assertIs(session.checkpoint, checkpoint)
                self.assertEqual(session.records, records)
        capture_window(session, WindowRead('delayed', 'a', ((2, 4),)))
        capture_window(session, AppliedEdit('delete', 'b', 'c', 1))
        finish_capture(session)
        self.assertEqual(verify_bundle(seal(session)).records[-2:],
                         (window('delayed', 'a', (2, 4)), EditFact('delete', 'b', 'c', 1)))
        with self.assertRaises(ValueError):
            capture_window(session, WindowRead('after-finish', 'c', ((1, 0),)))
        with self.assertRaises(ValueError):
            finish_capture(session)

    def test_premature_seal(self):
        session = start_capture('open', 'a', 1)
        with self.assertRaisesRegex(ValueError, 'finish the capture'):
            seal(session)
        capture_window(session, WindowRead('only', 'a', ((1, 5),)))
        finish_capture(session)
        self.assertEqual(verify_bundle(seal(session)).records, (window('only', 'a', (1, 5)),))
        with self.assertRaises(ValueError):
            start_capture('invalid', 'a', -1)
