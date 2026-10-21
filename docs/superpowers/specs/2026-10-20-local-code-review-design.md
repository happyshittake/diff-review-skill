# Local code review skill

## Approved intent and UI
A portable agent skill opens a local browser review for the user, collects draft inline/general feedback, and delivers the submitted review to the agent for revisions. Approved in conversation after the interactive `review-with-summary.html` mockup (2026-10-20).

- Compare uncommitted changes (staged + unstaged + untracked), branches, or commits. Clearly label comparison semantics: branches default merge-base to target (PR-style); commits compare exact trees.
- Immutable snapshot: comments refer to the exact reviewed content, not a live working tree.
- File sidebar and unified diff. Single-line comments and multiple-line comments on old/new sides. Clicking a code row or line number starts a selection; another click extends it, without Shift or a mode toggle. Clicking an already-selected line again toggles only that line off; keep other lines selected. Removing an interior line splits the selection into contiguous comment ranges; one draft comment per remaining range with no unselected context. Reserve toolbar layout space so selection does not shift code or scroll position. Clear resets all selected lines. Selection cannot cross files or sides.
- Agent-written overall summary only, collapsible. No per-file summaries: removed after the user's submitted review on 2026-10-21 to keep the skill lightweight. Explain the actual diff and uncertainty; never claim tests were run without evidence.
- The comment editor opens directly beneath the selected line/range, including when editing an existing comment; never at the bottom of the file.
- Inline/general drafts accumulate until Submit review. Review actions: Comment, Approve, Request changes. Submitted feedback includes snapshot identity, paths, side, line range, selected code context, summary, action, timestamp.
- Agent reads the submitted packet and addresses feedback, reporting what changed or why not. A revised review creates a new snapshot; never silently re-anchor an old comment.
- Default localhost only, no hosting/account/multi-user requirements. Expose only if requested, inspect available tunneling tools and choose appropriately; no provider-specific hardcoding. Protect access when exposed and disclose code privacy implications.

## Builder choices
Python 3 standard library + Git CLI for snapshot/server/feedback; vanilla browser JS/CSS based on approved layout. No LLM API in the server: the invoking agent supplies summaries. Bundle static resources; do not send repository content to external services. Source repository: `~/codes/diff-review-skill/` (user requested). Discover through a symlink at `~/.pi/agent/skills/local-code-review/`.

Session state lives outside the repository in a private directory. Show all data with textContent, validate API payloads and selected line ranges, authenticate all session endpoints with a random token, enforce same-origin writes, serve only explicit assets (never arbitrary repository paths), bound request size, persist review atomically. Do not checkout/reset/stash/change the index. Do not follow untracked symlinks or read secrets by default; warn about sensitive paths and provide exclusions. Reject unresolved merge conflicts clearly. Render binary changes as metadata, not corrupt text. Explain empty diffs/invalid refs and command errors.

## Delivery and lifecycle
CLI creates snapshot + prints session URL/state path; starts the server and opens browser on request. Drafts survive refresh within the session. Submit writes a durable review JSON; a bounded wait/read command returns it to the invoking agent. Document that a standalone skill cannot wake an already-idle agent by itself: wait while active, or resume by reading state on the next user turn. Do not promise automatic idle wake-up without a harness extension.

Provide stop/cleanup instructions; retain feedback until explicit cleanup. Default stays local and no tunnel is created during installation/testing.

## Non-goals
No GitHub integration, remote repository mutation, accounts, collaborative review, automatic code application, or IDE integration. No long-press gesture: two ordinary clicks are sufficient for the approved selection interaction.

## Verification
Real temporary Git repositories cover all comparison modes, staged/unstaged/untracked, renames/deletions, Unicode/spaces in paths, binary changes, empty repos/empty diffs, invalid refs, conflicts, exclusions/symlinks. HTTP tests verify authorization, CSRF/body/range validation, immutable snapshot and atomic submit/draft persistence. Browser tests use actual clicks for selection, inline editor placement/edit/re-attachment after file navigation, absence of per-file summaries, draft reload and submit, including old-side and reverse ranges. Skill scenarios verify invocation/comparison choice, honest summaries, feedback delivery and environment-adaptive tunneling guidance.
