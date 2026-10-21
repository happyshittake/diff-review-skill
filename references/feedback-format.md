# Review session data

`start` returns a `session` directory (mode 0700). It contains:

- `snapshot.json`: immutable captured diff, labels/resolved refs, one overall agent summary. Files have path, old_path, status, kind, hunks, added/deleted counts; hunk lines have type, old/new number or null, text, optional no_newline.
- `draft.json`: latest server-saved draft. **Not submitted; do not act on it.**
- `review.json`: atomically saved submission (mode 0600). Treat this as the user feedback packet.
- `secret.json`, `server.json`: bearer token/URL and process/port metadata. Never commit or publish them.
- `stopped.json`: server lifecycle marker. A stopped server does not invalidate saved feedback.

Example output from `wait` or `status` after submit:

```json
{
  "status": "submitted",
  "review": {
    "snapshot_id": "cfe2c48df9ebcbd42857",
    "comparison": {"repo": "/repo", "mode": "branches", "base": "resolved-merge-base-sha", "head": "resolved-target-sha"},
    "comments": [{
      "path": "src/checkout.ts",
      "side": "new",
      "start": 15,
      "end": 16,
      "text": "Use validated.items here too.",
      "context": [{"line": 15, "text": "const total = calculateTotal(items);"}, {"line": 16, "text": "return createOrder({ items, total });"}]
    }],
    "summary": "Please address the validation inconsistencies.",
    "decision": "request-changes",
    "viewed": ["src/checkout.ts"],
    "submitted_at": 1792507204.0
  }
}
```

Ranges are inclusive and must refer to consecutive displayed line numbers in one hunk, one file, and one side. The UI can unselect individual lines; if this splits a selection, it saves one comment per remaining contiguous range, excluding unselected lines from context. Old-side comments on renamed files use the displayed current path plus `side: old`; resolve old_path from snapshot.json when needed. Binary/excluded/metadata-only files support general feedback, not nonexistent inline ranges.

`decision` is `comment`, `approve`, or `request-changes`. It does not grant permission to merge/push/deploy. An empty review is permitted (e.g. Approve with no comments). `viewed` is a convenience checklist, not proof that every line is correct.

Server writes draft/review atomically and allows exactly one submitted packet per session. A second submit returns 409. Start a new snapshot/session after revisions.
