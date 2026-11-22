import base64
import json

from bundle.catalog import load_received
from bundle.envelope import verify_envelope, wrap_payload
from bundle.format import encode_payload
from bundle.intake import IntakeRejected
from storage import open_store
from tests.support import ProjectTest, scenario


class BundleTests(ProjectTest):
    def test_invalid_payload(self):
        payload = self.payload('stable')
        raw = encode_payload(payload)
        for invalid in (b'not json', wrap_payload('stable', b'{}'), wrap_payload('other', raw)):
            with self.subTest(invalid=invalid[:50]):
                with self.assertRaises(IntakeRejected):
                    self.receive(invalid)
                self.assertEqual(self.intake_count(), 0)
        good = self.raw('stable')
        received_no = self.receive(good)
        self.assertEqual(load_received(self.workspace.catalog, received_no).raw, good)

    def test_digest_mismatch(self):
        original = self.raw('stable')
        number = self.receive(original)
        envelope = json.loads(original)
        payload = json.loads(verify_envelope(original).payload)
        payload['records'][0]['rows'][0][1] = 99
        envelope['payload'] = base64.b64encode(json.dumps(payload).encode()).decode('ascii')
        with self.assertRaisesRegex(IntakeRejected, 'digest mismatch') as caught:
            self.receive(json.dumps(envelope).encode())
        self.assertEqual(self.intake_count(), 1)
        self.assertEqual(load_received(self.workspace.catalog, number).raw, original)
        scenario('v5.digest_mismatch', {'recording_id': 'stable', 'changed_mm': [0, 99]},
                 'digest mismatch', str(caught.exception).split('fixed content ')[-1],
                 1, self.intake_count(), ['bundle/envelope.py', 'bundle/intake.py', 'bundle/catalog.py'],
                 'The payload contains different bytes while the digest and original accepted row remain fixed.')

    def test_failed_intake_write_allocates_no_number(self):
        with open_store(self.workspace.catalog) as connection, connection:
            connection.execute('''CREATE TRIGGER block_intake BEFORE INSERT ON received_bundles
                                  BEGIN SELECT RAISE(ABORT, 'intake write failed'); END''')
        with self.assertRaisesRegex(IntakeRejected, 'intake write failed'):
            self.receive(self.raw('stable'))
        self.assertEqual(self.intake_count(), 0)
