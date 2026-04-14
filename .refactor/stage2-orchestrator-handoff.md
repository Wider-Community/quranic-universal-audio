# Stage 2 — Orchestrator Handoff (for fresh Claude Code session)

**Date**: 2026-04-14
**Branch**: `worktree-refactor+inspector-modularize` (WSL worktree)
**Working directory**: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/`
**Current HEAD**: `29a80e6` (Wave 9 — drop state.segStatsData + bridge)
**Project CLAUDE.md**: `inspector/CLAUDE.md` (gitignored — locally edited by prior agents; frontend tree section may drift slightly)

## TL;DR for the incoming orchestrator

You are taking over a multi-wave refactor driven by the `/refactor` skill. Stage 2 migrates the inspector frontend from vanilla-TS-imperative-DOM to Svelte 4, plus backend polish + Docker distribution. **Waves 0.5 through 9 are complete.** You are approaching **STOP-POINT 2** — before Wave 10 (history/rendering.ts rewrite, the most complex remaining Svelte migration). Confirm with the user before firing Wave 10.

Remaining waves: **10, 11**. Wave 10 owns history view full migration; Wave 11 owns final cleanup, cycle re-promote, dead-code sweep.

## State snapshot

### What's DONE

| Wave | Scope | Exit SHA | Notes |
|------|-------|----------|-------|
| 0.5 | Focused exploration of `segments/history/rendering.ts` | n/a (read-only) | Output: `.refactor/stage2-wave-0.5-handoff.md` |
| 1 | B02 fix + timestamps registry + cache.py + keyboard-guard | `fe60c35` | 9 commits + orchestrator chore `7961bae` |
| 2a | `config.py` INSPECTOR_DATA_DIR + vendor validators + Dockerfile+compose+.dockerignore + requirements-dev | `8d6e448` | 6 commits |
| 2-mid | Docker files moved from repo root → `inspector/` | `e98fb20` | 1 commit |
| 2b | `app.py` structured logging + 3 thin-routes + `save_seg_data` extract-method + magic-number sweep | `1a15c71` | 7 commits |
| 2-review | Sonnet + Opus + Haiku reviews | `46e1103` | follow-up commit only |
| 3 | Svelte 4 install + App.svelte + shared→lib migration + 6 shared primitives + CSS map | `566bb68` | 12 commits |
| 3-followup | `keyboard-guard` helper + `<AudioElement>` primitive + `<WaveformCanvas>` sub-ranging | `3e301f8` | 4 commits |
| 4 | Timestamps tab Svelte conversion (stores + 5 components) + 9 `timestamps/*.ts` deleted | `66f62d6` | 10 commits |
| 4-review | Sonnet + Opus reviews (both APPROVE) | `dd4c5c9` | follow-up commit only |
| stop-point-1 hotfix | Fix S2-B07 (audio/index.ts module-top-level DOM access) | `015556b` | 2 commits + 1 bug-log commit + 1 plan catch-up |
| 5 | Segments tab shell + filters + SegmentsList + navigation | (see wave-5 handoff) | ~10 commits |
| 6a | segAllData/segData store + chapter loading | (see wave-6a handoff) | ~6 commits |
| 6b | Filter stores + waveform-cache normalization (S2-B04) | (see wave-6b handoff) | ~6 commits |
| 7a | Edit modes (trim/split/merge/delete/reference) + EditOverlay | (see wave-7a handoff) | ~8 commits |
| 7b | History panel + undo — imperative retained | (see wave-7b handoff) | — |
| 8a.1 | ValidationPanel (store + Svelte component) | (see wave-8a.1 handoff) | — |
| 8a.2 | ValidationPanel review follow-ups + B1 DOM-clobber fixes | `970fa29` | — |
| 8b | StatsPanel + ChartFullscreen + StatsChart (store + 3 components) | `413b2d1` | 5 commits |
| 8b-review | Wave 8b review follow-ups (B1 chart double-fire + NB cleanup) | `2acf8ac` | 1 commit |
| 9 | S2-B05 fix + clearSegDisplay store-desync + save store + SavePreview.svelte + showPreview wiring + segStatsData deletion | `29a80e6` | 6 commits |

### What's IN PROGRESS

**STOP-POINT 2** — before Wave 10 (history/rendering.ts). Confirm with user before firing.

### What's NEXT

- Confirm with user: smoke Wave 9 changes (save preview visibility, undo no longer fires stale splitChainRef).
- Then fire **Wave 10**: full history view Svelte migration (`renderHistoryBatches`, `renderHistorySummaryStats`, `drawHistoryArrows`, `renderEditHistoryPanel`). This is the highest-risk remaining wave.

## User preferences discovered this session

1. **Sonnet OR OPUS for impl agents not always Opus by default**, depending on intensity of waves. User may pre-emptively override to Opus per wave — did so for Wave 4 (first Svelte tab conversion) and explicitly said "opus" when I asked about Wave 4. user's Wave-4 override extends that to "preemptive Opus for intense frontend work at user's call."
2. **Reviewers stay per plan** (Opus for judgment, Sonnet for pattern, Haiku for mechanical). Not a token-cost target.
3. **User approves each wave before firing.** Minimal replies ("confirm", "approve", "opus", "yes") — take them at face value. When you ask a yes/no, expect one-word replies.
4. **No testing (pytest / Vitest / Playwright)** — user declined upfront (S2-D07). Re-check before adding any test infrastructure.
5. **No bundle-size tracking** (S2-D14).
6. **User's declared stop-points**: end of Wave 4 (DONE, in progress) and before Wave 10 (`history/rendering.ts` rewrite). Nowhere else unless user explicitly requests.
7. **User's escalation**: "pause only before highest-risk phases" — between Waves 5-9 run autonomously through review gates.
8. **Commit style**: no Co-Authored-By trailers in inspector commits. Match existing `refactor(inspector):`/`feat(inspector):`/`fix(inspector):`/`chore(inspector):`/`docs(inspector):` conventions. Use HEREDOC for commit messages.
9. **User does smoke tests themselves** (not agents) — reviewers rely on manual-smoke reasoning only; agents never start the dev server.
10. **Data files in working tree** (untracked `data/recitation_segments/*/` dirs, modified `inspector/README.md`, `inspector/frontend/src/styles/validation.css`) — leave alone; they're the user's ongoing reciter data work, not refactor scope.

## Pattern decisions locked for Waves 5-10

Read them verbatim in `.refactor/stage2-wave-4-handoff.md` (top-of-document "Pattern notes for Waves 5-10" section). 8 patterns, one-liners:

1. Plain `writable<T>()` / `derived` — no factory wrappers
2. Shallow derivation; `$:` for single-component computed values
3. Stores for tab-scoped state; props for parent→child; events for child→parent
4. No DOM caches in state — `bind:this` + `querySelectorAll` in imperative update functions
5. Module-scope `Map` for WebAudio-style caches (non-reactive, S2-D12)
6. CSS vars as `style:` directives on tab root div (NOT `:root` via JS)
7. Keyboard via `<svelte:window on:keydown>` inside each tab + `shouldHandleKey(e, tab)` guard
8. **Hybrid 60fps**: Svelte for structure + imperative `updateHighlights()` method via `bind:this` for per-frame class toggles (new in Wave 4)

**S2-D33 carry-forwards** (from Wave-4 reviewers, in decisions log): Wave 5 cleanup of 3 orphan derived stores in `verse.ts`; factor `createPlaybackStore()` if patterns collide; **before Wave 7** replace `document.getElementById('audio-player'|'seg-audio-player')` DOM-lookups with refs/callbacks; **before Wave 8** use `{#each}` over 11 categories with open-state persistence.

## Pitfalls + reviewer-prompt refinements (learned from S2-B07)

- **Wave-3 regression missed by reviewers**: both Wave-3 Sonnet and Opus reviewers audited mount timing but only inside `DOMContentLoaded` handler bodies — they did NOT grep for module-top-level `mustGet` / `element.addEventListener` calls. When auditing future tab conversions (Waves 5, 11), **add to reviewer prompts**: `grep -n "^[a-zA-Z].*\\.addEventListener\\|^[a-zA-Z].*mustGet" src/<tab>/index.ts` — any hits mean module-top-level DOM access that'll run before `new App()` mounts. Same root cause will bite segments/index.ts or audio/index.ts if either gets touched again before being deleted in Waves 5/11.
- **`segments/index.ts` has its mustGet inside DOMContentLoaded handler** (correct). But when Wave 5 starts converting segments, the interim state may have some new Svelte component + the old `segments/index.ts` both active — watch for the mount-before-access invariant.
- **`timestamps/*.ts` is fully deleted** — zero risk there.

## Useful commands

```bash
# Enter the worktree
cd /mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/

# Git state
git log --oneline -20
git status --short

# Pre-flight gates (7 gates incl. cycle ceiling, typecheck, lint, build, global leak checks)
bash .refactor/stage2-checks.sh

# Build for smoke test
cd inspector/frontend && npm run build && cd ..
python3 app.py  # serves at localhost:5000

# Inspector production-mode uses debug=False by default; FLASK_ENV=development re-enables it
```

## File reading order (fresh orchestrator)

Minimum to be operational:

1. `.refactor/stage2-plan.md` — full plan (v3, post 3-model review). **Read in full.** Especially §2 invariants, §4 scope per wave, §5 target structure, §6 wave ordering, §9 stop-points, §10 decisions.
2. `.refactor/stage2-wave-4-handoff.md` — **the pattern-setter**. Top-of-document pattern notes are load-bearing for Waves 5-10.
3. `.refactor/stage2-decisions.md` — 33 decisions (S2-D01 through S2-D33); scan the full list.
4. `.refactor/stage2-bugs.md` — 1 OPEN (S2-B06 deferred cycles); S2-B01/B02/B04/B05/B07 all CLOSED. See wave handoffs for details.
5. `.refactor/stage2-orchestration-log.md` — per-agent budget + verdicts history.

Skim:
- `.refactor/stage2-css-migration-map.md` (load-bearing for Wave 11 cleanup)
- `.refactor/stage2-wave-{0.5, 1, 2, 3}-handoff.md` (later waves can look up as needed)
- `inspector/CLAUDE.md` (architecture principles — gitignored; frontend tree section may lag)

## Brief on the `/refactor` skill

The skill is at `~/.claude/skills/refactor/`. Key mechanics:

- **One implementation agent per wave** (max 3 sub-waves if a wave is genuinely large)
- **Reviewers at wave boundaries**: Sonnet always, Opus for heavy waves (per plan §6.2 table), Haiku for mechanical (Wave 2/3/11 primarily)
- **Stop-points**: declared in plan §9 (2 user-declared + systemic triggers like context ≥75%)
- **Shared docs**: orchestrator maintains 3 append-only `.refactor/stage2-*.md` files (bugs, decisions, orchestration-log) — agents append, never rewrite history
- **Plan-vs-delivery reconciliation** at every wave boundary via the handoff §6.3 template (11 sections, Wave 3 briefly drifted, Wave 4 restored conformity)
- **Pre-flight gate** `bash .refactor/stage2-checks.sh` runs 7 checks; must pass at every wave boundary
- **Cycle ceiling 16** (updated from 23 at Wave 1 start; now 14 actual + 2 buffer post-Wave 8b): `CYCLE_CEILING` env var in `stage2-checks.sh`. Decrements per wave as segments cycles dissolve; target 0 at Wave 11 re-promote.

## Immediate next actions for the fresh orchestrator

1. **Read** `.refactor/stage2-wave-9-handoff.md` (the freshest) + `stage2-plan.md` §4 Wave 10-11 + `stage2-decisions.md`.
2. **Do NOT re-fire Waves 0.5-9** — they're done.
3. **Confirm with user**: smoke Wave 9 (save preview visibility via store, S2-B05 undo regression test per wave-9 handoff §5). Wave 9 changes are low-risk (visibility store + null-outs) but confirm before Wave 10.
4. **STOP-POINT 2**: Wait for user to explicitly approve Wave 10 before firing. Wave 10 is the history view full Svelte migration — highest complexity remaining. Brief agent with wave-9 handoff §7 prerequisites + plan §4 Wave 10 scope.
5. If smoke surfaces a regression: diagnose via browser console, check for B1-class DOM clobbers or store-desync bugs. Log in `stage2-bugs.md` Section 3/4.

## Known clean state

- 7/7 pre-flight gates green at HEAD `29a80e6`
- Cycle count **14** (ceiling 16, 2-buffer)
- Zero `// NOTE: circular dependency` comments
- Zero `global` keyword outside `services/cache.py`
- Zero orphan `_URL_AUDIO_META` / `_phonemizer` references
- S2-B05 CLOSED (Wave 9)
- `state.segStatsData` field deleted (Wave 9 CF)
- Build: 480KB JS, 31KB CSS
- Timestamps tab: pure Svelte (5 components + 3 stores + 1 util)
- Segments + Audio tabs: unchanged Stage-1 imperative (still work via App.svelte hidden-div mount pattern)
- Backend: Docker-ready, structured logging, thin routes, `save_seg_data` decomposed
