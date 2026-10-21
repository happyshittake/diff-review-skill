# Local Code Review Implementation Plan

> Historical initial plan. User feedback on 2026-10-21 supersedes per-file summaries: use one overall summary and place the editor directly beneath the selected line/range. Current requirements are in the design spec; execution evidence is in `docs/verification.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Install a reusable skill that opens Git diffs in a local review webpage and returns submitted user feedback to the invoking agent.

**Architecture:** Python standard-library CLI captures an immutable Git snapshot and serves a bundled vanilla web UI. The agent provides overall/per-file summaries, starts/waits for the session, reads the submitted JSON, and handles feedback. No provider API or harness extension required.

**Tech Stack:** Python 3, Git CLI, vanilla JS/CSS, locally bundled daisyUI styles.

**Spec:** `../specs/2026-10-20-local-code-review-design.md`

## Global Constraints
- Default localhost; tunnels only on user request and chosen from available tools, not hardcoded.
- Always-on click-to-select line ranges; no Shift requirement or selection toggle.
- Preserve Git working tree/index; immutable snapshot and private durable session data.
- Overall/per-file summaries supplied by agent, with explicit uncertainty/test evidence.
- No external runtime/CDN calls or LLM API in the review server.
- Explicitly document standalone-skill idle wake-up limitations.

## Review Focus
- Git filenames with spaces/Unicode and rename/delete changes: preserve exact path identity.
- Old-side and reversed line ranges: attach to the right snapshot/side and reject nonexistent ranges.
- Untrusted code/feedback and hostile HTTP requests: no HTML execution, arbitrary file serving or cross-origin mutation.
- Refresh/server lifecycle: drafts survive refresh and submitted packet persists atomically.
- Sensitive/symlink/binary/conflicted inputs: no secret reads through symlinks, clear exclusions/metadata/errors.

---

### Task 1: Immutable Git snapshot
**Files:** create `scripts/review.py`, `tests/test_review.py`.
**Interfaces:** `capture(repo: Path, mode: str, base: str | None, head: str | None, excludes: list[str]) -> dict`; output includes snapshot id, mode, resolved refs, file paths/status/hunks with explicit old/new line numbers. Summary input is optional JSON with overall text and per-file what/why/notes.
- [ ] Write real-repo unit tests for worktree staged+unstaged+untracked, branch merge-base and exact-commit comparisons; invalid/option-like refs, rename/delete, Unicode/spaces, binary/symlink/excluded/conflicted/empty inputs.
- [ ] Run `python3 -m unittest discover -s tests -v`, confirm expected missing-implementation failures.
- [ ] Implement capture using subprocess argument arrays, explicit ref resolution, disabled Git external diff/textconv, bounded capture, safe untracked reads. Never mutate repo/index. Distinguish metadata-only files.
- [ ] Run all tests and inspect a representative snapshot for each mode.

### Task 2: Private session and feedback server
**Files:** extend `scripts/review.py`, `tests/test_review.py`.
**Interfaces:** CLI `start --repo PATH --mode worktree|branches|commits [--base REF --head REF] [--summaries FILE] [--exclude PATTERN] [--open]`; session start returns URL/state path. `wait --session PATH --timeout SECONDS` returns submitted feedback or explicit timeout. `stop --session PATH` shuts down owned server. HTTP GET session snapshot/draft; POST draft/submit; explicit bundled asset allowlist.
- [ ] Write HTTP tests for token auth, cross-origin and invalid bodies, bounded sizes, exact file/side/range validation, draft reload, immutable snapshot, duplicate submission, wait timeout/delivery and durable writes.
- [ ] Run tests, confirm new tests fail for absent session behavior.
- [ ] Implement loopback-only threaded server, random token/private state, atomic JSON writes, origin checks, bound request size, validated structured feedback with code context. Launch a detached owned server with logged errors; report startup failures. Keep token out of access logs.
- [ ] Run all tests; start/submit/read/stop a real temporary session.

### Task 3: Approved webpage
**Files:** create `assets/index.html`, `assets/app.js`, `assets/style.css`, locally bundled vendor CSS/license, browser smoke test fixture under `tests/`.
**Interfaces:** consume Task 1 snapshot and Task 2 draft/submit API; no Git parsing in browser. Draft contains inline comments `{path, side, start, end, text}` plus general summary and decision.
- [ ] Define browser checks: no selection toggle; actual code-text clicks select forward/reverse old/new range; comments retain range; clear/file change reset selection; drafts reload; summary follows file; submit delivers exact packet; user content renders as text.
- [ ] Verify missing UI fails the smoke scenario before implementation.
- [ ] Build the approved mockup layout with real data, collapsible overall/per-file agent summaries, always-on row/line-number selection, comment draft editing/removal, review action dialog, submit/error/loading/empty/binary states. Render safe DOM text; local static dependencies only. Do not discard typed text silently on another selection/file navigation.
- [ ] Run real browser click tests against temporary repo/session and inspect desktop/mobile screenshots once; batch any material corrections.

### Task 4: Skill workflow and installation verification
**Files:** create `SKILL.md`, `evals/evals.json`, `references/feedback-format.md`; tests/fixtures as needed.
**Interfaces:** portable skill entry with relative interpreter-invoked commands for capture/start/wait/stop and agent-written summary JSON; reusable across coding agents.
- [ ] Baseline-test prompts without this skill: worktree after feature, branch review, commit review plus requested expose. Record missing workflow behavior before authoring instructions.
- [ ] Write concise trigger-rich SKILL.md with comparison semantics, how to inspect changed code/write honest summaries, snapshot/start/open/wait/read/respond/new-review lifecycle, exact commands, draft vs submitted boundary, private-code safeguards, environment-adaptive tunnel selection and cleanup. No promises of waking an idle agent without extension support.
- [ ] Add 3 evaluation prompts with expected outputs and assertions for all comparison modes, feedback readback and tunnel choice without hardcoded provider.
- [ ] Run with-skill scenarios and compare expected behavior; run `python3 -m unittest discover -s tests -v` and CLI help end-to-end.
- [ ] Fresh independent reviewer checks connected code/security/lifecycle and requirements; address verified findings, rerun affected/full tests.
- [ ] Verify Pi frontmatter/discovery requirements; document `/reload` and `/skill:local-code-review` invocation. Report what was actually verified, known limits, and installed path. Do not create public tunnel or modify unrelated configuration.

## Execution note
Recommended: native execution in this session with one independent final reviewer. Snapshot/server/UI share one compact schema; per-task fresh implementation contexts add cost without useful isolation. User requested a Git project at `~/codes/diff-review-skill/`; repository initialized there and linked from `~/.pi/agent/skills/local-code-review/`. Keep source and tests in this repo. Do not push or configure a remote without a request.
