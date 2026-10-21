import http.client
import json
import subprocess
import sys
import unittest
import test_review as fixtures
from pathlib import Path

ROOT = fixtures.ROOT


class CLITests(fixtures.GitFixture):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), *map(str, args)], capture_output=True, text=True, timeout=10)

    def test_snapshot_start_wait_submit_stop(self):
        self.put('app.txt', 'first\nchanged\nthird\n')
        snapshot_path = self.repo / '.git/snapshot.json'
        result = self.cli('snapshot', '--repo', self.repo, '--output', snapshot_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot_path.stat().st_mode & 0o777, 0o600)
        result = self.cli('start', '--snapshot', snapshot_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.addCleanup(lambda: self.cli('stop', '--session', info['session']))
        session = Path(info['session'])
        self.assertEqual(session.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.cli('wait', '--session', session, '--timeout', '0.01').returncode, 2)
        token = json.loads((session / 'secret.json').read_text())['token']
        snapshot = json.loads(snapshot_path.read_text())
        packet = {'snapshot_id': snapshot['id'], 'comments': [
            {'path': 'app.txt', 'side': 'new', 'start': 2, 'end': 2, 'text': 'fix it'}
        ], 'summary': 'feedback', 'decision': 'request-changes', 'viewed': []}
        conn = http.client.HTTPConnection('localhost', info['port'])
        conn.request('POST', '/api/submit', json.dumps(packet), {'Authorization': 'Bearer ' + token, 'Origin': info['local_url'], 'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 200, response.read())
        conn.close()
        result = self.cli('wait', '--session', session, '--timeout', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['review']['comments'][0]['context'][0]['text'], 'changed')
        self.assertEqual(self.cli('stop', '--session', session).returncode, 0)
        self.assertTrue((session / 'review.json').exists(), 'Stopping must retain feedback')

    def test_summary_is_overall_only_even_with_legacy_file_explanations(self):
        self.put('app.txt', 'changed\n')
        snapshot = self.capture()
        snapshot['files'][0]['summary'] = {'what': 'old per-file explanation'}
        fixtures.review.apply_summaries(snapshot, {'overall': 'One overall explanation', 'files': {'app.txt': {'what': 'legacy'}}})
        self.assertEqual(snapshot['summary'], 'One overall explanation')
        self.assertNotIn('summary', snapshot['files'][0])

    def test_missing_summary_file_reports_error(self):
        result = self.cli('snapshot', '--repo', self.repo, '--summaries', self.repo / 'missing.json', '--output', self.repo / '.git/out.json')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
