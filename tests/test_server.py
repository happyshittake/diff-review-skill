import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from test_review import review


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(review, 'ReviewServer'), 'ReviewServer has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Path(self.tmp.name)
        self.snapshot = {'id': 'snapshot-1', 'files': [{'path': 'src/a.py', 'hunks': [{'lines': [
            {'old': 1, 'new': 1, 'type': ' ', 'text': '<script>unsafe()</script>'},
            {'old': None, 'new': 2, 'type': '+', 'text': 'new line'},
            {'old': 2, 'new': None, 'type': '-', 'text': 'old line'},
            {'old': 3, 'new': 3, 'type': ' ', 'text': 'context'},
        ]}]}]}
        (self.session / 'snapshot.json').write_text(json.dumps(self.snapshot))
        self.server = review.ReviewServer(self.session, 'test-token', 0)
        self.port = self.server.server_port
        self.origin = 'http://localhost:' + str(self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, payload=None, token='test-token', origin=True, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        h = {'Host': 'localhost:' + str(self.port)}
        if token is not None:
            h['Authorization'] = 'Bearer ' + token
        if origin:
            h['Origin'] = self.origin
        if payload is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        conn.request(method, path, json.dumps(payload) if payload is not None else None, h)
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def packet(self):
        return {'snapshot_id': 'snapshot-1', 'comments': [
            {'path': 'src/a.py', 'side': 'new', 'start': 1, 'end': 2, 'text': 'Please fix this'}
        ], 'summary': 'Overall feedback', 'decision': 'request-changes', 'viewed': ['src/a.py']}

    def test_auth_cookie_host_and_asset_allowlist(self):
        self.assertEqual(self.request('GET', '/api/snapshot', token=None)[0], 401)
        self.assertEqual(self.request('GET', '/api/snapshot', token='wrong')[0], 401)
        status, _, headers = self.request('GET', '/?token=test-token', token=None)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('GET', '/api/snapshot', token=None, headers={'Cookie': cookie})[0], 200)
        self.assertEqual(self.request('GET', '/api/snapshot', headers={'Host': 'attacker.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/../../etc/passwd')[0], 404)
        self.assertEqual(self.request('GET', '/snapshot.json')[0], 404)

    def test_csrf_and_invalid_payloads(self):
        self.assertEqual(self.request('POST', '/api/draft', self.packet(), origin=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/draft', self.packet(), headers={'Origin': 'https://evil.invalid'})[0], 403)
        for mutation in [
            {'snapshot_id': 'wrong'}, {'decision': 'execute'}, {'comments': 'not a list'},
            {'summary': 123}, {'viewed': ['unknown']},
        ]:
            self.assertEqual(self.request('POST', '/api/submit', {**self.packet(), **mutation})[0], 400)
        for mutation in [{'start': 0}, {'end': 5}, {'start': True}, {'side': 'both'},
                         {'path': '../etc/passwd'}, {'text': ''}, {'start': 3, 'end': 1}]:
            packet = self.packet()
            packet['comments'][0].update(mutation)
            self.assertEqual(self.request('POST', '/api/submit', packet)[0], 400, mutation)
        # Advertise an oversized body without flooding a socket the server rejects early.
        self.assertEqual(self.request('POST', '/api/draft', self.packet(), headers={'Content-Length': str(1024 * 1024 + 1)})[0], 413)
        self.assertFalse((self.session / 'review.json').exists())

    def test_draft_reload_submit_context_and_duplicate(self):
        packet = self.packet()
        self.assertEqual(self.request('POST', '/api/draft', packet)[0], 200)
        loaded = json.loads(self.request('GET', '/api/state')[1])
        self.assertEqual({k: loaded['draft']['comments'][0][k] for k in packet['comments'][0]}, packet['comments'][0])
        self.assertIsNone(loaded['review'])
        self.assertEqual(self.request('POST', '/api/submit', packet)[0], 200)
        saved = json.loads((self.session / 'review.json').read_text())
        self.assertEqual(saved['comments'][0]['context'], [
            {'line': 1, 'text': '<script>unsafe()</script>'}, {'line': 2, 'text': 'new line'}])
        self.assertEqual(saved['snapshot_id'], 'snapshot-1')
        self.assertIn('submitted_at', saved)
        self.assertEqual(self.request('POST', '/api/submit', packet)[0], 409)
        self.assertEqual(self.request('POST', '/api/draft', packet)[0], 409)
        self.assertEqual(json.loads(self.request('GET', '/api/snapshot')[1]), self.snapshot)
        self.assertEqual((self.session / 'review.json').stat().st_mode & 0o777, 0o600)

    def test_public_origin_is_explicit_https_and_local_only_configuration(self):
        self.assertEqual(self.request('POST', '/api/origin', {'origin': 'http://insecure.invalid'})[0], 400)
        status, body, _ = self.request('POST', '/api/origin', {'origin': 'https://review.example.invalid'})
        self.assertEqual(status, 200, body)
        status, _, _ = self.request('GET', '/api/snapshot', headers={'Host': 'review.example.invalid'})
        self.assertEqual(status, 200)
        packet = self.packet()
        headers = {'Host': 'review.example.invalid', 'Origin': 'https://review.example.invalid'}
        self.assertEqual(self.request('POST', '/api/draft', packet, headers=headers)[0], 200)
        self.assertEqual(self.request('POST', '/api/origin', {'origin': 'https://another.invalid'}, headers=headers)[0], 403)

    def test_old_side_ranges_and_hunk_gap(self):
        packet = self.packet()
        packet['comments'][0].update(side='old', start=1, end=3)
        self.assertEqual(self.request('POST', '/api/draft', packet)[0], 200)
        self.snapshot['files'][0]['hunks'] = [{'lines': [
            {'old': None, 'new': 1, 'type': '+', 'text': 'one'},
            {'old': None, 'new': 10, 'type': '+', 'text': 'ten'},
        ]}]
        self.server.snapshot = self.snapshot
        packet['comments'][0].update(side='new', start=1, end=10)
        self.assertEqual(self.request('POST', '/api/draft', packet)[0], 400)


if __name__ == '__main__':
    unittest.main()
