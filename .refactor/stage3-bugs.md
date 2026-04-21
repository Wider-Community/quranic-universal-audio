# Stage 3 — Bug Log

Append-only. Each row: id · phase seeded · title · context · disposition · fix status.

---

## Seeded at plan time

### B01 — `segments/history/undo.ts:210,212` Map-key cast no-op

**Phase seeded**: P3c (where fix lands implicitly via store migration).
**Context**: `state.segDirtyMap.delete(String(chapter) as unknown as number)` and same for `segOpLog`. Both maps typed `Map<number, …>`. Cast pattern creates a string key that SameValueZero never matches the numeric key in the map, so the `delete` is a no-op. Comment says "Legacy dual-key delete — state may have both numeric and string keys" but no writer call site in the current code passes a string key (all writers pass `number`). Writer call sites audit confirms this in P3a exploration.
**Disposition**: **SUSPECTED no-op — safe to remove**. Not a live correctness issue (the numeric-key delete on line 209/211 handles the real case). The cast is dead defence.
**Fix**: `segDirtyMap` + `segOpLog` migrate from `state.ts` into `lib/stores/segments/dirty.ts` as typed `Map<number, ...>` accessed only through a store write API that enforces `number`. The cast pattern disappears by construction.
**Fix status**: pending P3c.
**Fix SHA**: _(will be filled at P3c completion)_.
**Verification at P3c handoff**: grep `String(.*) as unknown as number` returns zero hits across `inspector/frontend/src/`. Explicit success criterion #19 in plan §1 enforces this post-Ph4.

**Stage-3-review note (Opus C4)**: Plan §9 added criterion #19 specifically for B01 fix verification (beyond the general #15 `as unknown as` ≤ 5 budget). Fix-SHA must be filled at Ph4 handoff.

---

### B02 — `_reverse_ignore` doesn't clear `ignored_categories` on undo

**Phase seeded**: Ph1 (surfaced during Sonnet quality review of `undo.py::_reverse_ignore`).
**Context**: `apply_reverse_op` branch for `ignore_issue` currently only restores `confidence` from the before-snapshot. But when the user ignored a category, `snapshotSeg` serialized `ignored_categories` into `targets_before` and `targets_after` too. After undo, `confidence` is restored but `ignored_categories` still contains the category — so `is_ignored_for(seg, category)` still returns True, and the validation UI continues to suppress the card even though the user has undone their "Ignore".
**Disposition**: **PRE-EXISTING BUG** — not introduced by Ph1's split, but the isolated 18-line `_reverse_ignore` helper is now the correct place to fix it. Low user-visibility (requires specific undo-of-ignore sequence + rechecking that category).
**Fix**: in `_reverse_ignore`, add `seg.pop("ignored_categories", None)` or restore from `snap_before.get("ignored_categories")` after confidence restoration.
**Fix status**: deferred; log for future pickup.
**Fix SHA**: _(not yet fixed — pre-existing, user can decide to address)_.
**Target phase for fix**: could be folded into Ph5 (`segments audio + data + history`) when undo paths are otherwise untouched, or into a dedicated follow-up commit. Not on Stage 3 critical path.
