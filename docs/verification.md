# Verification — updated 2026-10-21

## Submitted user review: round 1

The real submitted review for snapshot `2d5316311782136ddfe0` requested two changes: remove per-file summaries to reduce skill overhead, and open the comment box directly beneath the selected lines. Both are implemented across the UI, server summary input, skill instructions, docs, fixtures and eval expectations. The original submitted packet remains unchanged in its private session.

Regressions were observed failing before the fix: per-file summary metadata still attached, and composer outside the selected range. The updated browser smoke verifies new/edit comment placement, preservation through re-render/file navigation, and overall-only UI; all tests pass. Existing summary inputs with a legacy files map are accepted but per-file metadata is removed when applying the overall summary.

## Submitted user review: round 2

Review of snapshot `4c77ec5edcfc61d9ae70` requested click-again unselection. Clicking any selected line on the same side/hunk now clears the entire contiguous range, toolbar and aria-pressed states; clicking an unselected line still extends the range. Existing unsaved-comment discard confirmation remains in place. A real-click regression failed before the fix, then passed for range/single-line toggles, old-side number clicks and selecting again in reverse. Full Python suite remains 18/18 and the complete browser smoke passes.

## Submitted user review: round 3 (supersedes round 2 toggle semantics)

Review of snapshot `2b747345077552dd5086` reported selection jumping and asked that only the clicked line be unselected. Reproduced the jump: showing the previously hidden toolbar moved code. The toolbar now reserves fixed height, with disabled actions when empty; real browser checks assert unchanged row viewport position and scrollY after selecting a range.

Selection now tracks individual lines. Endpoint/interior/old-side clicks remove only that line; selecting beyond the edges extends the range without filling previous interior holes. Disjoint selections save separate contiguous comments, and a server-persisted context assertion proves removed lines are absent. These behaviors failed under the old implementation, then passed along with the complete browser suite and 18 Python tests. Inline new/edit placement and overall-only summary remain unchanged.

## Automated checks

- `python3 -m unittest discover -s tests -v`: 18 tests pass.
- `node --check assets/app.js`: pass (development-only; runtime does not require Node).
- SKILL.md YAML/name/description validated using Ruby's standard-library Psych; installation symlink checked. The official skill-creator Python validator could not run because its development dependency PyYAML is absent; no dependency was installed just for that check.
- `python3 tests/browser_smoke.py`: pass. Real browser clicks verified forward ranges, old-side reversed ranges, always-on selection, draft reload from server (browser fallback cleared), composer directly beneath selected lines (including edit and file navigation), overall-only explanation, inert source rendering, withheld sensitive content, mobile overflow, delayed-submit editing lock, and exact feedback/context returned by the agent wait command.
- Desktop 1440×1000 and mobile 390×844 captures inspected. Unified diff scrolls horizontally inside its own region on narrow screens; the document does not overflow.

## Fresh independent review

A separate read-only reviewer inspected source, spec, plan, skill and tests. No Critical issue was reported. Four Important and one Minor correctness issues were reproduced with failing regressions, then fixed:

1. File-to-directory transition could leak excluded child patches into a rename entry: exact literal pathspecs exclude descendants; parser also refuses multiple-file patches.
2. Unicode separators confused Git LF line numbering: split only at LF.
3. `diff.suppressBlankEmpty` could shift context line numbers: override the setting and validate hunk counts.
4. Editable feedback during an in-flight submit could disagree with the packet sent: freeze dialog controls and use one cloned packet for send/acknowledgment. Tested with an intentionally delayed response.
5. Source text containing a binary marker was misclassified: recognize actual metadata lines, not arbitrary substrings.

The full unit and real-browser suites passed after these changes.

## Skill consumer evaluation

Baseline fresh-agent exercise identified no existing persistent webpage/range/submit tool. A second fresh-agent exercise with SKILL.md successfully used all three comparison modes on disposable repositories, authored summaries, started a session, saved an unsubmitted draft, submitted a **synthetic test** packet through authenticated local HTTP, read matching context through bounded wait, and stopped/removed its fixture. Index/checkout/ref preservation checked.

Optional tunnel handling was tested **locally only** using a fictional HTTPS allowed origin: protected URL, secure cookie and untrusted-host rejection. No public tunnel/provider operation was performed. Skill instructions accurately explain active waits versus an idle agent and do not promise an automatic idle wake-up.

This is functional/consumer verification, not a statistical A/B skill-trigger benchmark. No token/time savings claim is made. Real human review feedback was not manufactured from the synthetic test packet.

## Decisions and known limits

- Source lives in the user-requested new repo, branch `feat/local-review`; no secondary worktree was created because there was no pre-existing application checkout to isolate. Risk: another worker using this path would share the working tree.
- The installing agent authors summaries; the server does not call an LLM or need credentials. Incorrect/absent source understanding can still make a summary inaccurate; the UI separates explanation from test evidence.
- Local bundled CSS instead of a build system; daisyUI 5.7.1 MIT. Design detector's gradient/stripe findings originate in unused vendor selectors, not rendered app components. One mobile 10px label was raised to 11px; modal shadow advisory retained from approved design.
- Filename-based sensitive-path protection is not a content secret scanner. Review source before exposing a session.
- One reviewer/tab; no multi-user draft merge. Inline text is only persisted after Add review comment; general feedback and added comments auto-save.
- Session data is retained in a private OS temporary directory until explicit/OS cleanup; copy it elsewhere if permanent retention is needed.
- Standalone skill cannot wake an idle agent. Keep bounded wait active or resume chat after Submit review.
- No live public tunnel, remote push, PR, deployment, or cross-platform GUI launch was tested/performed.
