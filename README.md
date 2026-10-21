# Local code review skill

A local PR-style browser review for coding agents. Review uncommitted changes, branches, or commits; leave single/multiple-line comments; submit feedback back to the agent.

## Install

Requires **Python 3.10+**, **Git**, and a browser. No pip/npm packages, account, or runtime CDN.

Clone this repo wherever you keep projects and link the directory into your agent's skills folder. On this machine:

```bash
ln -s ~/codes/diff-review-skill ~/.pi/agent/skills/local-code-review
```

The existing symlink is already installed. In Pi, run `/reload`, then:

```text
/skill:local-code-review buka review uncommitted changes
/skill:local-code-review compare main dengan feature/checkout
/skill:local-code-review compare commit OLD dengan NEW
```

Other Agent Skills-compatible agents can install this folder in their skill search path. The instructions/scripts are not tied to Pi APIs.

## What you get

- Immutable diff snapshot; no checkout, stash, reset or index changes.
- Combined staged + unstaged + untracked changes, PR-style branch merge-base comparisons, exact commit comparisons.
- One overall explanation authored by the invoking agent, not an external LLM service; no per-file summary workload.
- Always-on click-to-select ranges: click a row/number, then the last row, then Comment on selection. Click an already-selected line again to unselect only that line. Interior gaps create separate contiguous comment ranges. The toolbar reserves its space so selection doesn't move the code. Old/new sides remain separate.
- Comment editor directly beneath the selected line/range, including edit; saved drafts, Viewed checklist, general feedback and Comment/Approve/Request changes.
- **Submit review** saves an atomic JSON packet with line ranges and code context for the agent to read.
- Localhost by default. User-requested HTTPS tunnels supported with explicit allowed origin; skill chooses from available tools rather than prescribing a provider.

## CLI

```bash
python3 scripts/review.py --help
python3 scripts/review.py snapshot --repo /repo --mode branches --base main --head feature --output /private/snapshot.json
# The agent inspects the snapshot, writes summaries.json, then:
python3 scripts/review.py start --snapshot /private/snapshot.json --summaries /private/summaries.json --open
python3 scripts/review.py wait --session /returned/session/path --timeout 120
python3 scripts/review.py status --session /returned/session/path
python3 scripts/review.py stop --session /returned/session/path
```

`start --repo /repo --mode worktree --open` is also supported for manual use, but omitting agent-authored summaries displays explicit “not provided” messages. See [SKILL.md](SKILL.md) for summary format, full workflow, and tunnel setup; [feedback format](references/feedback-format.md) for the packet schema.

`wait` exits 0 on submitted feedback, 2 if still pending/stopped, 1 on error. It does **not** wake an already-idle agent: keep the bounded wait active or resume the chat after submit. This project is a skill, not a notification extension.

## Privacy and limits

The server binds only to 127.0.0.1; endpoints require a random session token and writes enforce Origin. Static assets are bundled. Repository files and comments are rendered as text, not HTML. A public tunnel is never started automatically; anyone with its complete token URL can read that session. Only share code you're allowed to expose.

Sensitive filenames and user exclusions are metadata-only; this is **not a secret-content scanner**. Untracked symlink targets aren't read. Binary/non-UTF-8 untracked files and large patches are metadata-only. Unresolved merge conflicts are rejected. Limit: 500 files, 4 MiB per displayed file/patch, 24 MiB snapshot, 1 MiB feedback packet. Range comments cannot span undisplayed gaps between hunks. Use general feedback for metadata-only files.

Drafts added with Add review comment and general feedback auto-save; wait for the saved status. Inline composer text not yet added isn't saved. One human reviewer/tab per session; no multi-user sync/merge. Stop retains private files in the OS temp directory; retain/copy them if needed before OS cleanup, and delete them explicitly when finished.

## Development

```bash
python3 -m unittest discover -s tests -v
node --check assets/app.js  # optional development syntax check; Node is not needed at runtime
python3 tests/demo.py      # starts a disposable real-Git demo; returns URL/session/repo
python3 tests/browser_smoke.py  # requires agent-browser; real click + reload + submit test
```

The UI uses bundled daisyUI **5.7.1** CSS (MIT; `assets/vendor-LICENSE.txt`) plus the project's stylesheet. No build step is needed.
