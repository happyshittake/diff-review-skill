#!/usr/bin/env python3
"""Private, dependency-free Git review sessions. Run --help for commands."""
import argparse
import fnmatch
import hashlib
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser
import subprocess
import sys
import time

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
MAX_FILE = 4 * 1024 * 1024
MAX_SNAPSHOT = 24 * 1024 * 1024
MAX_FILES = 500
SENSITIVE = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', 'id_rsa*',
             'id_ed25519*', '*credentials*', '*secrets*', '.netrc', '.npmrc')


def git(repo, *args, allow_failure=False, literal=True):
    try:
        proc = subprocess.run(['git', '--literal-pathspecs' if literal else '--no-literal-pathspecs',
                               '-c', 'core.quotepath=false', '-c', 'diff.suppressBlankEmpty=false',
                               '-c', 'color.ui=false', '-C', str(repo), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                              env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Git command timed out') from exc
    if proc.returncode and not allow_failure:
        raise ValueError(proc.stderr.decode('utf-8', 'replace').strip() or 'Git command failed')
    return proc.stdout if not proc.returncode else b''


def resolve(repo, ref):
    if not ref or ref.startswith('-'):
        raise ValueError('Invalid Git ref')
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()


def parse_hunks(patch):
    hunks = []
    old = new = 0
    remaining_old = remaining_new = 0
    lines = patch.split('\n')
    if sum(line.startswith('diff --git ') for line in lines) > 1:
        raise ValueError('Unexpected multiple files in one patch; refusing ambiguous line context')
    for line in lines:
        match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if match:
            if remaining_old or remaining_new:
                raise ValueError('Incomplete Git hunk')
            old, old_count, new, new_count = match.groups()
            old, new = int(old), int(new)
            remaining_old, remaining_new = int(old_count or 1), int(new_count or 1)
            hunks.append({'header': line, 'lines': []})
        elif hunks and line[:1] in (' ', '+', '-') and (remaining_old or remaining_new):
            sign = line[0]
            hunks[-1]['lines'].append({'type': sign, 'old': old if sign != '+' else None,
                                      'new': new if sign != '-' else None, 'text': line[1:]})
            old += sign != '+'
            new += sign != '-'
            remaining_old -= sign != '+'
            remaining_new -= sign != '-'
            if remaining_old < 0 or remaining_new < 0:
                raise ValueError('Invalid Git hunk line counts')
        elif line.startswith('\\ No newline') and hunks and hunks[-1]['lines']:
            hunks[-1]['lines'][-1]['no_newline'] = True
    if remaining_old or remaining_new:
        raise ValueError('Incomplete Git hunk')
    return hunks


def capture(repo, mode='worktree', base=None, head=None, excludes=None, include_sensitive=False):
    repo = Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip())
    if mode not in ('worktree', 'branches', 'commits'):
        raise ValueError('Unknown comparison mode')
    if git(repo, 'ls-files', '-u', '-z'):
        raise ValueError('Resolve merge conflicts before creating a review')
    if mode == 'worktree':
        base_sha = git(repo, 'rev-parse', '--verify', 'HEAD', allow_failure=True).decode().strip()
        # Git recognizes the empty-tree hash even in a repository without a commit.
        if not base_sha and git(repo, 'rev-parse', '--show-object-format').strip() == b'sha1':
            base_sha = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
        if not base_sha:
            # SHA-256 repositories need their own empty-tree object.
            proc = subprocess.run(['git', '-C', str(repo), 'hash-object', '-w', '-t', 'tree', '--stdin'],
                                  input=b'', capture_output=True, check=True)
            base_sha = proc.stdout.decode().strip()
        head_sha = 'working tree'
        revisions = [base_sha]
    else:
        base_sha, head_sha = resolve(repo, base), resolve(repo, head or 'HEAD')
        if mode == 'branches':
            base_sha = git(repo, 'merge-base', base_sha, head_sha).decode().strip()
        revisions = [base_sha, head_sha]
    raw = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '-M', *revisions, '--')
    parts = raw.decode('utf-8', 'surrogateescape').split('\0')
    entries = []
    i = 0
    while i < len(parts) and parts[i]:
        status_code, path = parts[i], parts[i + 1]
        i += 2
        old_path = None
        if status_code[0] in ('R', 'C'):
            old_path, path = path, parts[i]
            i += 1
        entries.append((status_code, path, old_path, False))
    if mode == 'worktree':
        tracked = {e[1] for e in entries}
        untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z').decode('utf-8', 'surrogateescape')
        entries.extend(('A', p, None, True) for p in untracked.split('\0') if p and p not in tracked)
    if len(entries) > MAX_FILES:
        raise ValueError(f'Too many changed files (limit {MAX_FILES}); use a smaller comparison')
    files = []
    for status_code, path, old_path, untracked in entries:
        item = {'path': path, 'old_path': old_path, 'status': status_code, 'kind': 'text', 'hunks': []}
        paths = [p for p in (path, old_path) if p]
        excluded = any(fnmatch.fnmatch(p, pattern) for p in paths for pattern in (excludes or []))
        sensitive = any(fnmatch.fnmatch(part.lower(), pattern) for p in paths for part in Path(p).parts for pattern in SENSITIVE)
        if excluded or (sensitive and not include_sensitive):
            item.update(kind='excluded', note='Excluded by pattern' if excluded else 'Sensitive filename: content withheld by default')
        elif untracked:
            full = repo / path
            if full.is_symlink() or any(p.is_symlink() for p in full.parents if p != repo):
                item.update(kind='symlink', note='Symlink target not read')
            elif full.stat().st_size > MAX_FILE:
                item.update(kind='large', note='File exceeds 4 MiB; content withheld')
            else:
                # Do not follow a symlink swapped in between the check and open.
                fd = os.open(full, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(fd, 'rb') as stream:
                    data = stream.read(MAX_FILE + 1)
                if len(data) > MAX_FILE:
                    item.update(kind='large', note='File exceeds 4 MiB')
                else:
                    try:
                        text = data.decode('utf-8')
                        if '\0' in text:
                            raise UnicodeError()
                        lines = text.split('\n')
                        if lines[-1] == '':
                            lines.pop()
                        item['hunks'] = [{'header': f'@@ -0,0 +1,{len(lines)} @@', 'lines': [
                            {'type': '+', 'old': None, 'new': n + 1, 'text': value,
                             **({'no_newline': True} if n == len(lines) - 1 and not text.endswith('\n') else {})}
                            for n, value in enumerate(lines)]}] if lines else []
                    except UnicodeError:
                        item.update(kind='binary', note='Binary or non-UTF-8 file; content not displayed')
        else:
            # A file replaced by a directory must not pull its excluded children into this patch.
            specs = [f':(top,literal){p}' for p in paths] + [f':(top,exclude,literal){p}/' for p in paths]
            patch = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--unified=5', '-M', *revisions, '--', *specs, literal=False)
            if len(patch) > MAX_FILE:
                item.update(kind='large', note='Patch exceeds 4 MiB; content withheld')
            elif any(re.match(rb'^Binary files .* differ$', line) or line == b'GIT binary patch' for line in patch.split(b'\n')):
                item.update(kind='binary', note='Binary file changed')
            else:
                item['hunks'] = parse_hunks(patch.decode('utf-8', 'replace'))
                if not item['hunks']:
                    item['note'] = 'Metadata-only change (rename, mode, submodule, or empty file)'
        item['added'] = sum(r['type'] == '+' for h in item['hunks'] for r in h['lines'])
        item['deleted'] = sum(r['type'] == '-' for h in item['hunks'] for r in h['lines'])
        files.append(item)
        if sum(len(json.dumps(f)) for f in files) > MAX_SNAPSHOT:
            raise ValueError('Snapshot exceeds 24 MiB; use exclusions or a smaller comparison')
    result = {'repo': str(repo), 'name': repo.name, 'mode': mode, 'base': base_sha, 'head': head_sha,
              'base_label': base or 'HEAD', 'head_label': head or head_sha, 'files': files,
              'created_at': time.time(), 'summary': ''}
    result['id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    return result


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def atomic_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_packet(snapshot, packet):
    if not isinstance(packet, dict) or packet.get('snapshot_id') != snapshot['id']:
        raise ValueError('Snapshot mismatch; reload this review')
    comments = packet.get('comments')
    if not isinstance(comments, list) or len(comments) > 500:
        raise ValueError('Expected at most 500 comments')
    summary = packet.get('summary', '')
    if not isinstance(summary, str) or len(summary) > 50000:
        raise ValueError('Summary must be text of at most 50000 characters')
    decision = packet.get('decision', 'comment')
    if decision not in ('comment', 'approve', 'request-changes'):
        raise ValueError('Invalid review decision')
    files = {f['path']: f for f in snapshot['files']}
    viewed = packet.get('viewed', [])
    if not isinstance(viewed, list) or len(viewed) > MAX_FILES or any(not isinstance(p, str) or p not in files for p in viewed):
        raise ValueError('Invalid viewed files')
    normalized = []
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError('Invalid comment')
        path, side = comment.get('path'), comment.get('side')
        start, end, text = comment.get('start'), comment.get('end'), comment.get('text')
        if not isinstance(path, str) or path not in files or side not in ('old', 'new'):
            raise ValueError('Unknown file or side')
        if type(start) is not int or type(end) is not int or not 1 <= start <= end or end - start > 10000:
            raise ValueError('Invalid line range')
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise ValueError('Comment must be nonempty text of at most 20000 characters')
        context = None
        for hunk in files[path]['hunks']:
            rows = {r[side]: r['text'] for r in hunk['lines'] if r.get(side) is not None}
            if all(n in rows for n in range(start, end + 1)):
                context = [{'line': n, 'text': rows[n]} for n in range(start, end + 1)]
                break
        if context is None:
            raise ValueError('Range must reference displayed lines in one hunk')
        normalized.append({'path': path, 'side': side, 'start': start, 'end': end, 'text': text.strip(), 'context': context})
    return {'snapshot_id': snapshot['id'], 'comments': normalized, 'summary': summary,
            'decision': decision, 'viewed': list(dict.fromkeys(viewed))}


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session, token, port=0, public_origin=None):
        self.session = Path(session)
        self.token = token
        self.snapshot = read_json(self.session / 'snapshot.json')
        self.lock = threading.RLock()
        self.cookie_name = 'review_' + hashlib.sha256(token.encode()).hexdigest()[:12]
        self.public_origin = public_origin
        super().__init__(('127.0.0.1', port), Handler)
        self.origins = {f'localhost:{self.server_port}': f'http://localhost:{self.server_port}',
                        f'127.0.0.1:{self.server_port}': f'http://127.0.0.1:{self.server_port}'}
        if public_origin:
            self.add_origin(public_origin)

    def add_origin(self, origin):
        if not isinstance(origin, str):
            raise ValueError('Public origin must be text')
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Public origin must be an exact HTTPS origin, without path or credentials')
        self.origins[parsed.netloc] = 'https://' + parsed.netloc
        return self.origins[parsed.netloc]


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalReview'

    def log_message(self, *_args):
        pass  # Session URLs contain credentials; never log request paths.

    def reply(self, status, data, mime='application/json', cookie=False):
        content = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            secure = '; Secure' if self.server.origins.get(self.headers.get('Host', ''), '').startswith('https:') else ''
            self.send_header('Set-Cookie', f'{self.server.cookie_name}={self.server.token}; HttpOnly; SameSite=Strict; Path=/{secure}')
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        if self.headers.get('Host') not in self.server.origins:
            self.reply(403, {'error': 'Untrusted host; configure --public-origin for a tunnel'})
            return False
        candidates = [self.headers.get('Authorization', '').removeprefix('Bearer ')]
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
            if self.server.cookie_name in cookies:
                candidates.append(cookies[self.server.cookie_name].value)
        except Exception:
            pass
        parsed = urlsplit(self.path)
        if self.command == 'GET' and parsed.path == '/':
            candidates.extend(parse_qs(parsed.query).get('token', []))
        if not any(secrets.compare_digest(c, self.server.token) for c in candidates):
            self.reply(401, {'error': 'Open the complete session URL supplied by the agent'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        if path == '/api/snapshot':
            self.reply(200, self.server.snapshot)
        elif path == '/api/state':
            self.reply(200, {'draft': read_json(self.server.session / 'draft.json'),
                             'review': read_json(self.server.session / 'review.json')})
        elif path in ('/', '/app.js', '/style.css', '/vendor.css'):
            filename = 'index.html' if path == '/' else path[1:]
            mime = 'text/html; charset=utf-8' if path == '/' else 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8'
            try:
                self.reply(200, (ASSETS / filename).read_bytes(), mime, cookie=path == '/')
            except FileNotFoundError:
                self.reply(404, {'error': 'UI asset is not installed'})
        else:
            self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            return
        if self.headers.get('Origin') != self.server.origins[self.headers['Host']]:
            self.reply(403, {'error': 'Cross-origin write rejected'})
            return
        path = urlsplit(self.path).path
        if path == '/api/stop':
            self.reply(200, {'stopped': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == '/api/origin':
            if self.headers['Host'] not in (f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}') or self.headers.get('Authorization') != 'Bearer ' + self.server.token:
                self.reply(403, {'error': 'Configure public origin through the local CLI only'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2048:
                    raise ValueError('Origin configuration too large')
                self.connection.settimeout(5)
                origin = self.server.add_origin(json.loads(self.rfile.read(size)).get('origin'))
                self.reply(200, {'url': origin + '/?token=' + self.server.token})
            except (ValueError, AttributeError, OSError) as exc:
                self.reply(400, {'error': str(exc)})
            return
        if path not in ('/api/draft', '/api/submit'):
            self.reply(404, {'error': 'Not found'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                self.reply(413, {'error': 'Review payload must be between 1 byte and 1 MiB'})
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Expected application/json')
            self.connection.settimeout(10)
            packet = validate_packet(self.server.snapshot, json.loads(self.rfile.read(size)))
            with self.server.lock:
                if (self.server.session / 'review.json').exists():
                    self.reply(409, {'error': 'Review already submitted; create a new snapshot for revisions'})
                    return
                if path == '/api/submit':
                    packet.update(submitted_at=time.time(), comparison={k: self.server.snapshot.get(k) for k in ('repo', 'mode', 'base', 'head')})
                    atomic_json(self.server.session / 'review.json', packet)
                else:
                    atomic_json(self.server.session / 'draft.json', packet)
            self.reply(200, {'ok': True})
        except (ValueError, TypeError, UnicodeError, OSError) as exc:
            self.reply(400, {'error': str(exc)})


def apply_summaries(snapshot, source):
    if source is None:
        return snapshot
    if not isinstance(source, dict) or not isinstance(source.get('overall', ''), str):
        raise ValueError('Summary requires overall text')
    snapshot['summary'] = source.get('overall', '')
    for item in snapshot['files']:
        item.pop('summary', None)
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('snapshot', 'start'):
        p = sub.add_parser(name)
        p.add_argument('--repo', default='.')
        p.add_argument('--mode', choices=['worktree', 'branches', 'commits'], default='worktree')
        p.add_argument('--base')
        p.add_argument('--head')
        p.add_argument('--exclude', action='append', default=[])
        p.add_argument('--include-sensitive', action='store_true', help='Only with explicit user permission')
        p.add_argument('--summaries', type=Path)
        if name == 'snapshot':
            p.add_argument('--output', type=Path, required=True)
        else:
            p.add_argument('--snapshot', type=Path, help='Use an already captured snapshot unchanged')
            p.add_argument('--open', action='store_true')
            p.add_argument('--public-origin', help='Exact HTTPS origin of a user-requested tunnel')
    for name in ('wait', 'status', 'stop', 'serve', 'allow-origin'):
        p = sub.add_parser(name)
        p.add_argument('--session', type=Path, required=True)
        if name == 'wait':
            p.add_argument('--timeout', type=float, default=120)
        if name == 'serve':
            p.add_argument('--public-origin')
        if name == 'allow-origin':
            p.add_argument('--origin', required=True, help='Exact HTTPS origin from the requested tunnel')
    args = parser.parse_args(argv)
    try:
        if args.command in ('snapshot', 'start'):
            snapshot_path = getattr(args, 'snapshot', None)
            snapshot = read_json(snapshot_path) if snapshot_path else capture(args.repo, args.mode, args.base, args.head, args.exclude, args.include_sensitive)
            if not snapshot:
                raise ValueError('Snapshot file not found or empty')
            if args.summaries and not args.summaries.is_file():
                raise ValueError('Summary file does not exist')
            apply_summaries(snapshot, read_json(args.summaries) if args.summaries else None)
            if args.command == 'snapshot':
                atomic_json(args.output, snapshot)
                print(json.dumps({'snapshot': str(args.output), 'id': snapshot['id'], 'files': len(snapshot['files'])}))
                return 0
            session = Path(tempfile.mkdtemp(prefix='local-code-review-'))
            session.chmod(0o700)
            atomic_json(session / 'snapshot.json', snapshot)
            atomic_json(session / 'secret.json', {'token': secrets.token_urlsafe(32)})
            command = [sys.executable, str(Path(__file__).resolve()), 'serve', '--session', str(session)]
            if args.public_origin:
                command.extend(['--public-origin', args.public_origin])
            with (session / 'server.log').open('wb') as log:
                process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
            for _ in range(100):
                info = read_json(session / 'server.json')
                if info:
                    if args.open:
                        webbrowser.open(info['url'])
                    print(json.dumps(info))
                    return 0
                if process.poll() is not None:
                    raise ValueError('Server startup failed: ' + (session / 'server.log').read_text())
                time.sleep(0.05)
            raise ValueError(f'Server startup timed out; inspect {session}/server.log')
        session = args.session.resolve()
        if args.command == 'serve':
            token = read_json(session / 'secret.json')['token']
            with ReviewServer(session, token, public_origin=args.public_origin) as server:
                local = f'http://localhost:{server.server_port}'
                public = (args.public_origin or local).rstrip('/')
                atomic_json(session / 'server.json', {'session': str(session), 'url': public + '/?token=' + token,
                                                       'local_url': local, 'pid': os.getpid(), 'port': server.server_port})
                try:
                    server.serve_forever()
                finally:
                    atomic_json(session / 'stopped.json', {'stopped_at': time.time()})
            return 0
        if args.command in ('stop', 'allow-origin'):
            info, secret = read_json(session / 'server.json'), read_json(session / 'secret.json')
            conn = http.client.HTTPConnection('localhost', info['port'], timeout=5)
            endpoint = '/api/stop' if args.command == 'stop' else '/api/origin'
            body = json.dumps({'origin': args.origin}) if args.command == 'allow-origin' else None
            conn.request('POST', endpoint, body=body, headers={'Authorization': 'Bearer ' + secret['token'], 'Origin': info['local_url'], 'Content-Type': 'application/json'})
            response = conn.getresponse()
            print(response.read().decode())
            conn.close()
            return 0 if response.status == 200 else 1
        deadline = time.monotonic() + (max(0, args.timeout) if args.command == 'wait' else 0)
        while True:
            packet = read_json(session / 'review.json')
            if packet:
                print(json.dumps({'status': 'submitted', 'review': packet}, ensure_ascii=True))
                return 0
            if time.monotonic() >= deadline:
                print(json.dumps({'status': 'stopped' if (session / 'stopped.json').exists() else 'pending', 'session': str(session)}))
                return 2
            time.sleep(0.25)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
