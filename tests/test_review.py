from dataclasses import replace

from archive.readback import read
from archive.schema import SignedDraft
from capture.edit_log import EditFact
from capture.observations import CapturedWindow
from review.decision import MissingOrigins, ReconcileRejected
from tests.support import ProjectTest, SCROLL_LINES, evidence, lines_of, scenario, window


class ReviewTests(ProjectTest):
    def test_complete_cross_state(self):
        number = self.receive(self.raw('scroll-complete'))
        signed = self.decide(number)
        self.assertIsInstance(signed, SignedDraft)
        self.assertEqual(lines_of(signed), SCROLL_LINES)
        self.assertEqual(signed.received_no, number)
        self.assertEqual((signed.receipt.result_no, signed.receipt.received_no), (signed.result_no, number))
        self.assertGreater(signed.receipt.first_receipt_no, 0)
        reopened = read(self.workspace.archive, signed.result_no)
        self.assertEqual(reopened, signed)
        self.assertEqual(self.archive_counts(), (1, 4, 1))
        scenario('v3', {'start_mm': [7, 11, 7, 13], 'move': [4, 1], 'pre_rewrite_screen': 4},
                 SCROLL_LINES, lines_of(signed), SCROLL_LINES, lines_of(reopened),
                 ['review/origin.py', 'review/eligibility.py', 'review/coverage.py', 'archive/readback.py'],
                 'Manually trace the original rows through the move. The fourth screen position still holds the original third row before the rewrite.')

    def test_original_value_missing(self):
        number = self.receive(self.raw('scroll-missing'))
        result = self.decide(number)
        self.assertIsInstance(result, MissingOrigins, 'SHIFT_DRAFT_FALSE_SIGN')
        self.assertEqual(result, MissingOrigins(number, (3,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        scenario('v4', {'start_mm': [7, 11, 7, 13], 'move': [4, 1], 'rewrite': [4, 19]},
                 [3], list(result.positions), [0, 0, 0], list(self.archive_counts()),
                 ['review/eligibility.py', 'review/decision.py', 'archive/publish.py'],
                 'Original row 3 was observed only after its reading was replaced.')

    def test_move_only(self):
        signed = self.decide(self.receive(self.raw('move-only')))
        self.assertEqual(lines_of(signed), [(1, 3, 'm1', 'moved', 2, 2),
                                           (2, 8, 'm1', 'moved', 3, 2),
                                           (3, 3, 'm1', 'moved', 1, 2)])

    def test_insert_delete(self):
        signed = self.decide(self.receive(self.raw('insert-delete')))
        self.assertEqual(lines_of(signed), [(1, 5, 'i3', 'post', 2, 5),
                                           (2, 9, 'i0', 'keep-old', 2, 1),
                                           (3, 12, 'i3', 'post', 4, 5)])

    def test_after_delete_replacement(self):
        number = self.submit(self.without_windows('insert-delete', 'keep-old'))
        self.assertEqual(self.decide(number), MissingOrigins(number, (2,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_same_value_rewrite(self):
        number = self.receive(self.raw('same-value'))
        self.assertEqual(self.decide(number), MissingOrigins(number, (3,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_capture_order(self):
        payload = evidence('order', 'a', 2, EditFact('move', 'a', 'b', 2, 1),
                           window('z-first', 'b', (1, 4), (2, 3)),
                           window('a-delayed', 'a', (1, 3), (2, 4)))
        signed = self.decide(self.submit(payload))
        self.assertEqual(lines_of(signed), [(1, 3, 'b', 'z-first', 2, 2), (2, 4, 'b', 'z-first', 1, 2)])

    def test_conflicting_observations(self):
        payload = self.payload('scroll-complete')
        records = tuple(window('shifted', 's1', (1, 13), (2, 50))
                        if isinstance(entry, CapturedWindow) and entry.window_id == 'shifted' else entry
                        for entry in payload.records)
        number = self.submit(replace(payload, records=records))
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide(number)
        self.assertEqual(caught.exception.code, 'evidence_conflict')
        self.assertIn('row 1', str(caught.exception))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_all_missing(self):
        number = self.submit(evidence('unread', 'a', 3))
        self.assertEqual(self.decide(number), MissingOrigins(number, (1, 2, 3)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_missing_state_transition(self):
        payload = self.payload('scroll-complete')
        records = tuple(entry for entry in payload.records
                        if not isinstance(entry, EditFact) or entry.kind != 'move')
        number = self.submit(replace(payload, records=records))
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide(number)
        self.assertEqual(caught.exception.code, 'invalid_history')
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_unobserved_gap(self):
        head = window('whole', 'a', (1, 0), (2, 6))
        first = EditFact('move', 'a', 'b', 1, 2)
        second = EditFact('rewrite', 'b', 'c', 2)
        healthy = self.decide(self.submit(evidence('tail', 'a', 2, head, first, second)))
        self.assertEqual([line.mm for line in healthy.lines], [0, 6])
        before = self.archive_counts()
        invalid = self.submit(evidence('tail', 'a', 2, head, second))
        with self.assertRaises(ReconcileRejected) as caught:
            self.decide(invalid)
        self.assertEqual(caught.exception.code, 'invalid_history')
        self.assertEqual(self.archive_counts(), before)
        scenario('v6.unobserved_gap', {'observed_state': 'a', 'retained_edit': ['b', 'c']},
                 'invalid_history', caught.exception.code, list(before), list(self.archive_counts()),
                 ['bundle/intake.py', 'review/history.py', 'review/decision.py'],
                 'State b cannot be reached from a after removing the first edit, despite complete initial observations.')

    def test_unknown_window_state(self):
        for extra in (window('bad', 'missing', (1, 1)), window('bad', 'a', (2, 1))):
            with self.subTest(extra=extra):
                payload = evidence('unknown', 'a', 1, window('whole', 'a', (1, 0)), extra)
                with self.assertRaises(ReconcileRejected) as caught:
                    self.decide(self.submit(payload))
                self.assertEqual(caught.exception.code, 'invalid_history')
        self.assertEqual(self.archive_counts(), (0, 0, 0))
