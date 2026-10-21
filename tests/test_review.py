import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('review', ROOT / 'scripts/review.py')
review = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC and SPEC.loader and (ROOT / 'scripts/review.py').exists():
    SPEC.loader.exec_module(review)


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.put('app.txt', 'first\nsecond\nthird\n')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE).decode()

    def put(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def capture(self, mode='worktree', base=None, head=None, excludes=None):
        self.assertTrue(hasattr(review, 'capture'), 'capture() has not been implemented')
        return review.capture(self.repo, mode, base, head, excludes or [])


class GitTests(GitFixture):
    def test_combined_worktree_and_untracked_are_immutable(self):
        self.put('app.txt', 'first\nstaged\nthird\n')
        self.git('add', 'app.txt')
        self.put('app.txt', 'first\nstaged\nunstaged\n')
        self.put('space ü.txt', 'hello\nworld\n')
        index_before = (self.repo / '.git/index').read_bytes()
        snapshot = self.capture()
        files = {f['path']: f for f in snapshot['files']}
        self.assertEqual(set(files), {'app.txt', 'space ü.txt'})
        rows = files['app.txt']['hunks'][0]['lines']
        self.assertIn('staged', [r['text'] for r in rows])
        self.assertIn('unstaged', [r['text'] for r in rows])
        self.assertEqual(files['space ü.txt']['hunks'][0]['lines'][1]['new'], 2)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index_before)
        self.put('app.txt', 'later\n')
        self.assertIn('unstaged', [r['text'] for r in rows])
        self.assertTrue(snapshot['id'])

    def test_branch_merge_base_and_exact_commits(self):
        self.git('checkout', '-b', 'feature')
        self.put('feature.txt', 'feature\n')
        self.git('add', '.')
        self.git('commit', '-m', 'feature')
        feature = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', 'main')
        self.put('main.txt', 'main\n')
        self.git('add', '.')
        self.git('commit', '-m', 'main')
        branch = self.capture('branches', 'main', 'feature')
        self.assertEqual([f['path'] for f in branch['files']], ['feature.txt'])
        self.assertEqual(branch['base'], self.base)
        exact = self.capture('commits', 'main', feature)
        self.assertEqual({f['path'] for f in exact['files']}, {'main.txt', 'feature.txt'})

    def test_rename_delete_binary_and_sensitive(self):
        self.git('mv', 'app.txt', 'renamed ü.txt')
        (self.repo / 'blob.bin').write_bytes(b'\x00\x01\x02')
        self.put('.env', 'SECRET=must-not-leak\n')
        self.put('ignored.txt', 'exclude-me\n')
        (self.repo / 'outside').symlink_to('/etc/passwd')
        snapshot = self.capture(excludes=['ignored.txt'])
        by_path = {f['path']: f for f in snapshot['files']}
        self.assertEqual(by_path['renamed ü.txt']['old_path'], 'app.txt')
        self.assertEqual(by_path['blob.bin']['kind'], 'binary')
        self.assertEqual(by_path['.env']['kind'], 'excluded')
        self.assertEqual(by_path['outside']['kind'], 'symlink')
        self.assertEqual(by_path['ignored.txt']['kind'], 'excluded')
        self.assertNotIn('must-not-leak', json.dumps(snapshot))
        self.assertNotIn('exclude-me', json.dumps(snapshot))
        self.git('reset', '--hard', 'HEAD')
        (self.repo / 'app.txt').unlink()
        deleted = {f['path']: f for f in self.capture()['files']}['app.txt']
        self.assertEqual(deleted['status'], 'D')
        self.assertTrue(all(r['new'] is None for r in deleted['hunks'][0]['lines']))

    def test_empty_and_invalid_ref(self):
        self.assertEqual(self.capture()['files'], [])
        for bad in ['not-a-ref', '--output=/tmp/nope']:
            with self.assertRaises(ValueError):
                self.capture('commits', bad, 'HEAD')

    def test_unborn_repository(self):
        empty = self.repo / 'empty'
        empty.mkdir()
        subprocess.run(['git', '-C', str(empty), 'init'], capture_output=True, check=True)
        (empty / 'new.txt').write_text('new\n')
        self.assertTrue(hasattr(review, 'capture'), 'capture() has not been implemented')
        snapshot = review.capture(empty, 'worktree', None, None, [])
        self.assertEqual(snapshot['files'][0]['path'], 'new.txt')

    def test_directory_transition_cannot_leak_excluded_children_into_rename(self):
        self.put('config', 'configuration\n')
        self.git('add', 'config')
        self.git('commit', '-m', 'config')
        self.git('mv', 'config', 'config.txt')
        self.put('config/.env', 'SECRET=do-not-leak\n')
        self.put('config/private.txt', 'excluded-content\n')
        self.git('add', '.')
        snapshot = self.capture(excludes=['config/private.txt'])
        self.assertNotIn('do-not-leak', json.dumps(snapshot))
        self.assertNotIn('excluded-content', json.dumps(snapshot))
        renamed = next(f for f in snapshot['files'] if f['path'] == 'config.txt')
        self.assertEqual(renamed['hunks'], [])

    def test_unicode_separators_preserve_git_lf_lines(self):
        self.put('app.txt', 'one\u2028two\nthree\n')
        self.put('untracked.txt', 'one\u2028two\nthree\n')
        by_path = {f['path']: f for f in self.capture()['files']}
        for name in ('app.txt', 'untracked.txt'):
            added = [r for h in by_path[name]['hunks'] for r in h['lines'] if r['type'] == '+']
            self.assertEqual([(r['new'], r['text']) for r in added], [(1, 'one\u2028two'), (2, 'three')])

    def test_diff_config_cannot_shift_blank_context_line_numbers(self):
        self.put('app.txt', 'first\n\nthird\n')
        self.git('commit', '-am', 'blank line')
        self.git('config', 'diff.suppressBlankEmpty', 'true')
        self.put('app.txt', 'first\n\nchanged\n')
        rows = self.capture()['files'][0]['hunks'][0]['lines']
        self.assertIn({'type': ' ', 'old': 2, 'new': 2, 'text': ''}, rows)
        self.assertEqual(next(r['new'] for r in rows if r['text'] == 'changed'), 3)

    def test_binary_marker_in_source_is_not_binary_metadata(self):
        self.put('app.txt', 'return b"Binary files " in patch\nGIT binary patch\n')
        item = self.capture()['files'][0]
        self.assertEqual(item['kind'], 'text')
        self.assertTrue(item['hunks'])

    def test_conflict_rejected(self):
        self.git('checkout', '-b', 'other')
        self.put('app.txt', 'other\n')
        self.git('commit', '-am', 'other')
        self.git('checkout', 'main')
        self.put('app.txt', 'main\n')
        self.git('commit', '-am', 'main')
        subprocess.run(['git', '-C', str(self.repo), 'merge', 'other'], capture_output=True)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.capture()


if __name__ == '__main__':
    unittest.main()
