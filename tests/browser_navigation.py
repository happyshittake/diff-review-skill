"""Navigation regressions against a private real-Git snapshot. Requires agent-browser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

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
    (repo / 'long-line.txt').write_text('x' * 250 + ' distantmarker end\n')
    (repo / 'unicode.txt').write_text('İSTANBUL specialCase\n')
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
        browser('eval', 'document.querySelectorAll(".file").forEach(b=>{if(b.getAttribute("aria-label").startsWith(pathA+" · "))b.click()})')
        check('document.querySelector("#filename").textContent===pathA && document.querySelector(".file.active").getAttribute("aria-current")==="true"', 'full selected path and active semantics')
        browser('check', '#viewed')
        check('document.querySelector(".file.active .change").textContent.includes("✓")', 'viewed marker updates without navigation')
        check('!window.XSS && !document.querySelector("#files img")', 'filenames rendered as inert text')
        check('document.querySelector(".file.active").getAttribute("aria-label").includes("Viewed") && document.querySelector(".file.active").getAttribute("aria-label").includes(" · M")', 'accessible name includes viewed state and change status')
        for width in (1440, 390):
            browser('set', 'viewport', str(width), '1000')
            check('document.documentElement.scrollWidth<=innerWidth', 'no document overflow at ' + str(width))
            browser('screenshot', '--full', str(ARTIFACTS / ('sidebar-' + str(width) + '.png')))
        browser('set', 'viewport', '1440', '1000')
        check('document.querySelectorAll("input[type=search]").length===1', 'one unified search input')
        for width in (1440, 390):
            browser('set', 'viewport', str(width), '1000')
            browser('fill', '#review-search', 'distantmarker')
            browser('click', '.search-result')
            check('(()=>{const mark=document.querySelector(".search-destination mark").getBoundingClientRect(), viewport=document.querySelector("#lines").getBoundingClientRect();return mark.left>=viewport.left-1 && mark.right<=viewport.right+1})()', 'long-line result reveals the actual match at ' + str(width))
        browser('set', 'viewport', '1440', '1000')
        browser('fill', '#review-search', 'old-name')
        check('document.querySelectorAll(".file").length===1 && document.querySelector(".file").getAttribute("aria-label").startsWith("new-name.ts · ") && !document.querySelector(".search-result")', 'renamed old path matches without code matches')
        browser('fill', '#review-search', 'BATCHMATCH')
        check('document.querySelectorAll(".file").length===1 && document.querySelectorAll(".search-result").length===100 && document.querySelector("#search-status").textContent.includes("205")', 'case-insensitive code-only search and bounded results')
        browser('click', '#more-matches')
        check('document.querySelectorAll(".search-result").length===200', 'next result batch reachable')
        browser('click', '#more-matches')
        check('document.querySelectorAll(".search-result").length===205', 'all matches reachable')
        browser('fill', '#review-search', 'never-display-navigation')
        check('!document.querySelector(".file") && !document.querySelector(".search-result")', 'sensitive contents excluded')
        for query in ('binarysentinel', 'largesentinel', 'no-such-code'):
            browser('fill', '#review-search', query)
            check('!document.querySelector(".file") && !document.querySelector(".search-result")', 'no unavailable or nonexistent contents: ' + query)
        browser('fill', '#review-search', '.env')
        browser('click', '.file')
        check('document.querySelector("#lines").textContent.includes("Sensitive") && !document.querySelector(".search-result")', 'metadata-only path remains navigable')
        browser('fill', '#review-search', '[]')
        check('document.querySelectorAll(".file").length===5 && document.querySelectorAll(".search-result").length===5', 'literal punctuation and union deduplication')
        browser('fill', '#review-search', 'i\u0307stanbul')
        check('document.querySelectorAll(".search-result").length===1 && document.querySelector(".search-result mark").textContent==="İSTANBUL" && document.querySelector(".search-snippet").textContent==="İSTANBUL specialCase"', 'Unicode case expansion highlights original source without corruption')
        browser('fill', '#review-search', '<script>')
        check('document.querySelectorAll(".search-result").length===4 && !window.XSS && !document.querySelector("#search-results script")', 'search snippets are inert text')
        browser('click', '#clear-search')
        browser('eval', 'document.querySelectorAll(".file").forEach(b=>{if(b.getAttribute("aria-label").startsWith(pathA+" · "))b.click()})')
        browser('click', '.row[data-new="2"] .source')
        browser('click', '#comment-range')
        browser('fill', '#comment-text', 'Keep this unsaved review text')
        browser('eval', 'window.savedRow=document.querySelector(".row.selected");window.savedComposer=document.querySelector("#composer");window.savedDraft=JSON.stringify(draft);window.savedSelection=[...selection.lines].join();')
        browser('eval', 'window.searchFetches=[];window.originalFetch=window.fetch;window.fetch=(...args)=>{searchFetches.push(args[0]);return originalFetch(...args)}')
        browser('fill', '#review-search', 'batchmatch')
        browser('click', '#clear-search')
        check('searchFetches.length===0', 'typing and clearing search make no requests')
        check('savedRow===document.querySelector(".row.selected") && savedComposer===document.querySelector("#composer") && !savedComposer.classList.contains("hidden") && document.querySelector("#comment-text").value==="Keep this unsaved review text" && JSON.stringify(draft)===savedDraft && [...selection.lines].join()===savedSelection', 'typing and clearing preserve composer nodes, draft and selection')
        browser('fill', '#review-search', 'batchmatch')
        browser('eval', 'window.confirm=()=>false')
        browser('click', '.search-result')
        check('document.querySelector("#filename").textContent===pathA && document.querySelector("#comment-text").value==="Keep this unsaved review text" && savedRow===document.querySelector(".row.selected")', 'cancelled cross-file jump preserves editor and file')
        browser('eval', 'window.confirm=()=>true')
        browser('click', '.search-result')
        check('document.querySelector("#filename").textContent==="many.txt" && document.querySelector("#review-search").value==="batchmatch" && document.activeElement.classList.contains("search-destination")', 'accepted jump retains query and focuses exact line')
        browser('fill', '#review-search', 'second hunk validate')
        browser('eval', 'document.querySelectorAll(".search-result").forEach(b=>{if(b.dataset.file===String(snapshot.files.findIndex(f=>f.path===pathA)))b.click()})')
        check('document.querySelector(".search-destination").dataset.new==="30" && document.querySelector(".search-destination").dataset.hunk==="1"', 'second-hunk destination is precise')
        browser('click', '.row[data-new="30"] .source')
        browser('click', '#comment-range')
        browser('fill', '#comment-text', 'Same-file navigation keeps me')
        browser('eval', 'document.querySelectorAll(".search-result").forEach(b=>{if(b.dataset.file===String(current))b.click()})')
        check('document.querySelector("#comment-text").value==="Same-file navigation keeps me" && document.querySelector(".row.selected") && !document.querySelector("#composer").classList.contains("hidden")', 'same-file jump preserves selection and composer')
        browser('click', '#cancel-comment')
        browser('fill', '#review-search', 'context 2')
        check('[...document.querySelectorAll(".search-result")].some(b=>b.textContent.includes("old line 2")) && [...document.querySelectorAll(".search-result")].some(b=>b.textContent.includes("new line 29"))', 'removed and context results carry correct coordinates')
        browser('click', '#clear-search')
        check('document.querySelectorAll(".file").length===snapshot.files.length && !document.querySelector("#lines mark") && !document.querySelector(".search-destination")', 'clear restores all files and removes search-only styling')
        for width in (1440, 390):
            browser('set', 'viewport', str(width), '1000')
            browser('fill', '#review-search', 'validate')
            check('document.documentElement.scrollWidth<=innerWidth', 'search has no overflow at ' + str(width))
            browser('screenshot', '--full', str(ARTIFACTS / ('search-' + str(width) + '.png')))
        browser('set', 'viewport', '1440', '1000')
        browser('click', '#clear-search')
        browser('eval', 'document.querySelectorAll(".file").forEach(b=>{if(b.getAttribute("aria-label").startsWith(pathA+" · "))b.click()})')
        browser('hover', '#review-search')
        browser('eval', 'window.hintStart=0;window.hintElapsed=null;new MutationObserver(()=>{if(!document.querySelector("#file-path-hint").hidden)hintElapsed=performance.now()-hintStart}).observe(document.querySelector("#file-path-hint"),{attributes:true,attributeFilter:["hidden"]});document.querySelector(".file.active").addEventListener("mouseenter",()=>hintStart=performance.now());')
        browser('hover', '.file.active')
        check('document.querySelector("#file-path-hint").hidden', 'no immediate hover hint')
        browser('wait', '--fn', '!document.querySelector("#file-path-hint").hidden')
        check('hintElapsed>=990 && document.querySelector("#file-path-hint").textContent===pathA', 'truncated path hint delayed at least one second')
        browser('screenshot', str(ARTIFACTS / 'tooltip-desktop.png'))
        browser('press', 'Escape')
        check('document.querySelector("#file-path-hint").hidden', 'Escape dismisses visible hint')
        browser('fill', '#review-search', 'README.md')
        browser('hover', '.file')
        time.sleep(1.2)
        check('document.querySelector("#file-path-hint").hidden', 'untruncated path has no hint')
        browser('focus', '.file')
        check('document.querySelector("#file-path-hint").hidden', 'untruncated keyboard focus has no hint')
        browser('click', '#clear-search')
        browser('hover', '.file.active')
        browser('hover', '#review-search')
        time.sleep(1.2)
        check('document.querySelector("#file-path-hint").hidden', 'leaving cancels pending tooltip')
        for action in ('escape', 'scroll', 'resize', 'redraw'):
            browser('eval', 'document.querySelector(".file.active").dispatchEvent(new MouseEvent("mouseenter"))')
            if action == 'escape':
                browser('eval', 'document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))')
            elif action == 'redraw':
                browser('fill', '#review-search', 'batchmatch')
            else:
                browser('eval', 'window.dispatchEvent(new Event(' + json.dumps(action) + '))')
            time.sleep(1.2)
            check('document.querySelector("#file-path-hint").hidden', action + ' cancels pending tooltip')
            browser('click', '#clear-search')
        browser('focus', '.file.active')
        check('!document.querySelector("#file-path-hint").hidden', 'truncated keyboard focus shows immediately')
        browser('set', 'viewport', '390', '844')
        browser('focus', '#review-search')
        browser('focus', '.file.active')
        check('(()=>{const r=document.querySelector("#file-path-hint").getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight && document.documentElement.scrollWidth<=innerWidth})()', 'tooltip fits mobile viewport')
        browser('screenshot', '--full', str(ARTIFACTS / 'tooltip-mobile.png'))
        browser('set', 'viewport', '1440', '1000')
        browser('fill', '#review-search', 'batchmatch')
        browser('focus', '.search-result')
        browser('press', 'Enter')
        check('document.querySelector("#filename").textContent==="many.txt"', 'keyboard activates search result')
        browser('focus', '#clear-search')
        browser('press', 'Enter')
        check('document.querySelector("#review-search").value===""', 'keyboard clears unified search')
        browser('click', '.headline .finish')
        browser('click', '#submit-review')
        browser('wait', '--text', 'Review submitted:')
        browser('fill', '#review-search', 'batchmatch')
        browser('click', '.search-result')
        check('document.querySelector("#viewed").disabled && !document.querySelector(".line-add") && document.querySelectorAll(".num[aria-pressed]:not(:disabled)").length===0', 'search navigation after submission remains read-only')
        subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), 'stop', '--session', info['session']], check=True, capture_output=True)
        git(repo, 'add', '.')
        git(repo, 'commit', '-m', 'capture all fixture changes')
        info = start(repo)
        browser('open', info['url'])
        browser('wait', '--text', 'Summary of changes')
        browser('fill', '#review-search', 'nothing')
        browser('click', '#clear-search')
        check('!document.querySelector(".file") && document.querySelector("#file-view").classList.contains("hidden") && !document.querySelector("#empty").classList.contains("hidden")', 'empty snapshot supports search and clear')
    finally:
        if info:
            subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), 'stop', '--session', info['session']], capture_output=True)
        browser('close')
