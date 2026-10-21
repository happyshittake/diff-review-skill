"""Real browser clicks against a disposable Git review. Requires agent-browser."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / '.superpowers/browser-smoke'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
info = json.loads(subprocess.check_output([sys.executable, str(ROOT / 'tests/demo.py')]))
env = {**os.environ, 'AGENT_BROWSER_SESSION': 'review-smoke-' + str(os.getpid())}


def browser(*args):
    proc = subprocess.run(['agent-browser', *args], env=env, capture_output=True, text=True, timeout=35)
    if proc.returncode:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc.stdout


def check(expression, message):
    browser('eval', 'if(!(' + expression + '))throw Error(' + json.dumps(message) + ');' + json.dumps('PASS: ' + message))
    print('PASS:', message)


try:
    browser('open', info['url'])
    browser('wait', '--text', 'Summary of changes')
    browser('set', 'viewport', '1440', '1000')
    check('document.querySelector("#overall-summary").textContent.includes("validasi cart")', 'overall summary')
    check('!document.querySelector("#select-mode")', 'selection always on')
    browser('eval', 'window.selectionBefore={top:document.querySelector(".row.add").getBoundingClientRect().top,scroll:window.scrollY}')
    browser('click', '.row[data-new="2"] .source')
    browser('click', '.row[data-new="6"] .source')
    check('Math.abs(document.querySelector(".row.add").getBoundingClientRect().top-window.selectionBefore.top)<1 && window.scrollY===window.selectionBefore.scroll', 'selecting a range does not move code or scroll position')
    check('document.querySelectorAll(".row.selected").length===5', 'forward code-text range')
    browser('click', '.row[data-new="6"] .source')
    check('[...document.querySelectorAll(".row.selected")].map(n=>n.dataset.new).join(",")==="2,3,4,5"', 'unselecting endpoint removes only that line')
    browser('click', '.row[data-new="4"] .source')
    check('[...document.querySelectorAll(".row.selected")].map(n=>n.dataset.new).join(",")==="2,3,5"', 'unselecting interior line preserves other selected lines')
    browser('click', '#comment-range')
    browser('fill', '#comment-text', 'Only selected lines, not the removed one.')
    browser('click', '#comment-form button[type="submit"]')
    browser('wait', '--text', 'tersimpan, belum dikirim')
    check('[...document.querySelectorAll(".thread-head")].some(n=>n.textContent.includes("lines 2–3")) && [...document.querySelectorAll(".thread-head")].some(n=>n.textContent.includes("line 5")) && document.querySelectorAll(".thread-head").length===2', 'split selection saves separate exact contiguous comment ranges')
    saved_split = json.loads((Path(info['session']) / 'draft.json').read_text())['comments']
    assert [(c['start'], c['end']) for c in saved_split] == [(2, 3), (5, 5)]
    assert [r['line'] for c in saved_split for r in c['context']] == [2, 3, 5]
    print('PASS: server feedback context excludes the unselected line')
    browser('find', 'first', '#lines .thread-head button:last-child', 'click')
    browser('find', 'first', '#lines .thread-head button:last-child', 'click')
    browser('click', 'button.num[aria-label="new line 2"]')
    browser('click', 'button.num[aria-label="new line 2"]')
    check('document.querySelectorAll(".row.selected").length===0 && document.querySelector("#comment-range").disabled && !document.querySelector("button.num[aria-pressed=true]")', 'last selected line toggles off and disables comment action')
    browser('click', '.row[data-new="6"] .source')
    browser('click', '.row[data-new="2"] .source')
    check('document.querySelectorAll(".row.selected").length===5', 'range can be selected again in reverse after toggle off')
    browser('click', '#comment-range')
    check('document.querySelector(".range-end").nextElementSibling === document.querySelector("#composer") && document.querySelector("#composer").parentElement.id === "lines"', 'composer attached directly beneath selected range')
    browser('fill', '#comment-text', 'Gunakan validated.items sepanjang flow.')
    browser('click', '#comment-form button[type="submit"]')
    browser('wait', '--text', 'tersimpan, belum dikirim')
    # Remove browser fallback so reload proves the HTTP draft survived, not just sessionStorage.
    browser('eval', 'sessionStorage.clear()')
    browser('open', info['local_url'])
    browser('wait', '--text', 'Gunakan validated.items sepanjang flow.')
    check('document.querySelector(".thread-head").textContent.includes("2–6")', 'server draft survives reload with range')
    browser('click', '.thread-head button')
    check('document.querySelector("#composer").previousElementSibling.dataset.new === "6"', 'editing opens composer at original line')
    browser('fill', '#comment-text', 'Gunakan validated.items sepanjang flow.')
    browser('click', '#comment-form button[type="submit"]')
    browser('scroll', 'down', '450')
    browser('click', 'button.num[aria-label="old line 4"]')
    browser('click', 'button.num[aria-label="old line 2"]')
    check('document.querySelector("#range-selection").textContent.includes("old lines 2–4")', 'old-side reverse range')
    browser('click', 'button.num[aria-label="old line 3"]')
    check('[...document.querySelectorAll(".row.selected")].map(n=>n.dataset.old).join(",")==="2,4"', 'old-side toggle removes only clicked line')
    browser('click', '.file[data-file="2"]')
    check('!document.querySelector(".file-explanation") && !document.querySelector("#file-what") && document.querySelector("#overall-summary").textContent.includes("validasi cart")', 'overall summary only, no per-file explanation')
    browser('click', '.row[data-new="1"] .source')
    browser('click', '#comment-range')
    check('document.querySelector(".range-end").nextElementSibling === document.querySelector("#composer")', 'composer survives file navigation and reattaches inline')
    browser('click', '#cancel-comment')
    check('!window.XSS && document.querySelector("#lines").textContent.includes("<script>")', 'code rendered as inert text')
    browser('click', '.file[data-file="1"]')
    check('document.querySelector("#lines").textContent.includes("Sensitive filename") && !document.body.textContent.includes("never-display")', 'sensitive content withheld')
    browser('click', '.file[data-file="0"]')
    browser('screenshot', '--full', str(ARTIFACTS / 'desktop.png'))
    browser('set', 'viewport', '390', '844')
    browser('screenshot', '--full', str(ARTIFACTS / 'mobile.png'))
    check('document.documentElement.scrollWidth <= window.innerWidth', 'mobile document has no horizontal overflow')
    browser('set', 'viewport', '1440', '1000')
    browser('click', '.headline .finish')
    browser('fill', '#review-summary', 'Please revise the validation flow.')
    browser('click', 'input[value="request-changes"]')
    browser('eval', 'window.realFetch=window.fetch; window.fetch=(path,options)=>path==="/api/submit"?new Promise((resolve,reject)=>{window.releaseSubmission=()=>window.realFetch(path,options).then(resolve,reject)}):window.realFetch(path,options)')
    browser('click', '#submit-review')
    browser('wait', '--fn', 'typeof window.releaseSubmission === "function"')
    check('document.querySelector("#review-summary").disabled && [...document.querySelectorAll("input[name=decision]")].every(n=>n.disabled)', 'feedback editing locked during delayed submission')
    browser('eval', 'window.releaseSubmission(); "released"')
    browser('wait', '--text', 'Review submitted: request-changes')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), 'wait', '--session', info['session'], '--timeout', '1'], capture_output=True, text=True, check=True)
    packet = json.loads(result.stdout)['review']
    assert packet['decision'] == 'request-changes'
    assert packet['summary'] == 'Please revise the validation flow.'
    assert packet['comments'][0]['start'] == 2 and packet['comments'][0]['end'] == 6
    assert packet['comments'][0]['context'][0]['text'] == '  const validated = validateItems(items);'
    print('PASS: browser Submit review delivers exact feedback + code context to agent wait')
    print('Screenshots:', ARTIFACTS)
finally:
    subprocess.run([sys.executable, str(ROOT / 'scripts/review.py'), 'stop', '--session', info['session']], capture_output=True)
    browser('close')
