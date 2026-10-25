"""Navigation regressions against a private real-Git snapshot. Requires agent-browser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / '.superpowers/browser-navigation'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'AGENT_BROWSER_SESSION': 'review-navigation-' + str(os.getpid())}
info = None


def browser(*args):
    proc = subprocess.run(['agent-browser', *args], env=env, capture_output=True, text=True, timeout=35)
    if proc.returncode:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc.stdout


def check(expression, message):
    browser('eval', 'if(!(' + expression + '))throw Error(' + json.dumps(message) + ');true')
    print('PASS:', message, flush=True)


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


def start(repo):
    return json.loads(subprocess.check_output([sys.executable, str(ROOT / 'scripts/review.py'),
                                              'start', '--repo', str(repo)]))


with tempfile.TemporaryDirectory(prefix='review-navigation-') as temp:
    repo = Path(temp)
    long_dir = 'apps/storefront/src/features/checkout/components/payment-methods'
    other_dir = 'apps/admin/src/features/orders/components/payment-methods'
    paths = [long_dir + '/PaymentMethodSelector.tsx', other_dir + '/PaymentMethodSelector.tsx',
             long_dir + '/' + 'unusually-long-payment-method-name-' * 3 + '.json']
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Navigation test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    for path in paths + ['README.md', 'old-name.ts']:
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(''.join('context %d\n' % i for i in range(1, 40)))
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'initial')
    for path in paths + ['README.md']:
        file = repo / path
        file.write_text(file.read_text().replace('context 2\n', 'validate [] <script>window.XSS=true</script>\n')
                        .replace('context 30\n', 'second hunk validate\n'))
    git(repo, 'mv', 'old-name.ts', 'new-name.ts')
    (repo / 'new-name.ts').write_text((repo / 'new-name.ts').read_text() + 'renamed marker\n')
    (repo / '.env').write_text('SECRET=never-display-navigation\n')
    (repo / '<img src=x onerror=window.XSS=true>.txt').write_text('literal markup []\n')
    (repo / 'many.txt').write_text(''.join('batchmatch %d\n' % i for i in range(205)))
    (repo / 'binary.bin').write_bytes(b'\x00binarysentinel')
    (repo / 'large.txt').write_text('largesentinel' * 400000)
    try:
        info = start(repo)
        browser('open', info['url'])
        browser('wait', '--text', 'Summary of changes')
        browser('set', 'viewport', '1440', '1000')
        browser('eval', 'window.pathA=' + json.dumps(paths[0]) + ';window.pathB=' + json.dumps(paths[1]) + ';')
        check('[...document.querySelectorAll(".file-name")].filter(n=>n.textContent==="PaymentMethodSelector.tsx").length===2', 'duplicate basenames are readable')
        check('[...document.querySelectorAll(".file-directory")].some(n=>n.textContent==="Repository root") && [...document.querySelectorAll(".file-directory")].some(n=>n.textContent==="' + long_dir + '")', 'directory context and root labels')
        browser('eval', 'document.querySelectorAll(".file").forEach(b=>{if(b.getAttribute("aria-label")===pathA)b.click()})')
        check('document.querySelector("#filename").textContent===pathA && document.querySelector(".file.active").getAttribute("aria-current")==="true"', 'full selected path and active semantics')
        browser('check', '#viewed')
        check('document.querySelector(".file.active .change").textContent.includes("✓")', 'viewed marker updates without navigation')
        check('!window.XSS && !document.querySelector("#files img")', 'filenames rendered as inert text')
        for width in (1440, 390):
            browser('set', 'viewport', str(width), '1000')
            check('document.documentElement.scrollWidth<=innerWidth', 'no document overflow at ' + str(width))
            browser('screenshot', '--full', str(ARTIFACTS / ('sidebar-' + str(width) + '.png')))
    finally:
        if info:
            subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), 'stop', '--session', info['session']], capture_output=True)
        browser('close')
