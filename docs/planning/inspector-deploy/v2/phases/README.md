# Inspector v2 — Phases

Skimmable per-phase summaries. Each phase doc is a one-page contract: **goal, deliverables, acceptance, verification, risks** — no rationale, no internal decisions.

For the *why* of any decision, jump to the detailed v2 docs in the parent folder:
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) — architecture
- [`inspector-data-storage.md`](../inspector-data-storage.md) — file IO + bucket semantics
- [`inspector-state-management.md`](../inspector-state-management.md) — state machine, catalog
- [`inspector-publish-pipeline.md`](../inspector-publish-pipeline.md) — publish fan-out
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) — roles + admin actions
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) — Space + bucket setup, smoke tests
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) — what gets deleted/added/modified
- [`inspector-deferred.md`](../inspector-deferred.md) — explicitly punted items

## Order + status

| # | Phase | Status | Blocks |
|---|---|---|---|
| 1 | [Foundation](01-foundation.md) | done (Phase 5 carries: repo `data/` cleanup; D19 carries: 14 legacy tests; D20 carries: legacy bucket shards) | 2 |
| 2 | [Deployable image + read-only deploy](02-deployable-image.md) | not started | 3, 4 |
| 3 | [Auth + claim flow](03-auth-and-claims.md) | not started | 4, 5 |
| 4 | [Save migration](04-save-migration.md) | not started | 5 |
| 5 | [Publish pipeline](05-publish-pipeline.md) | not started | 6 |
| 6 | [Public dashboard + reusable picker](06-public-dashboard.md) | not started | 7 |
| 7 | [Admin dashboard + cleanup](07-admin-dashboard.md) | not started | — |

Phases land sequentially. Phase 2 unblocks 3 and 4 in parallel only if you have someone to split work across — solo, run sequentially. Phase 6 depends on the reciter taxonomy / catalog schema refactor landing out-of-band — the doc is intentionally taxonomy-agnostic and will be refined against the concrete schema before implementation starts.

For a visual reference of the reciter lifecycle (public + admin views, transitions, state-preserving actions), see [`state-machine.md`](state-machine.md).

**Already complete (out of phase scope):**
- HF dev bucket created and mount tested.

## Phase doc schema

Each phase doc follows this skeleton — use it for new phases or doc edits:

```markdown
# Phase N — <Title>

> One-sentence elevator summary.

**Status:** not started | in progress | done
**Depends on:** Phase X (or: foundation complete)
**Blocks:** Phase Y

## Goal
2–4 sentences of what is true at the end of this phase.

## Deliverables
- [ ] Concrete artifact (file / endpoint / service / workflow)
- [ ] ...

## Out of scope
- What's deferred to a later phase, even if related.

## Acceptance criteria
- [ ] Testable condition
- [ ] ...

## Verification
Exact commands / smoke tests / file checks that prove acceptance.

## Risks
- Brief bullets — link to detailed doc for depth.

## Reference
- Detailed-doc cross-links for the *why*.
```

Anti-patterns:
- Don't recapitulate architecture rationale here.
- Don't enumerate every internal helper — only externally observable deliverables (endpoints, files, behaviors).
- Don't put commit-by-commit task lists — those go in PR descriptions.
- If a phase needs detailed plumbing notes, write a separate `phase-N-notes.md` next to it; don't bloat the contract.

## At plan time — write the detailed plan with help

These phase docs are **contracts**, not detailed implementation plans. When it's time to actually build a phase, the detailed plan lives elsewhere (a working doc, a PR description, a tracking issue) and gets written collaboratively. Treat the phase doc as input to that process, not the output.

Approach the detailed-plan stage like the [doc-coauthoring](../../../../.claude/skills/doc-coauthoring/) workflow:

1. **Question first, then commit.** Before locking down the detailed plan, ask clarifying questions. Sample prompts the writer should run through:
   - "Are any deliverables ambiguous? Each one should be a single concrete artifact."
   - "Does any deliverable belong in a different phase? Smaller phases are cheaper to land."
   - "Has any acceptance criterion become unverifiable since the contract was written?"
   - "Are there hidden dependencies on later phases that should be flagged here?"
   - "Has any decision in the detailed v2 docs drifted from this phase doc?" (Drift means update this doc first, then write the plan.)

2. **Use subagents as advisors and explorers, not as ghostwriters.** Good uses:
   - **Explore:** "What does the current `inspector/services/save.py` look like? Where are the resolver call-sites?" (Spawn an Explore agent so the planner sees real code, not memory.)
   - **Critique:** "Here's my draft plan for Phase N. Push back on scope, sequencing, and over-engineering — bias toward shipping smaller increments." (Spawn a general-purpose agent with the draft + the canonical decisions list as input.)
   - **Verify:** "Does this plan match the canonical decisions in the v2 detailed docs? Find contradictions." (Same shape as the original canonicalization sweep.)
   The planner stays in the driver's seat — agents don't decide, they widen the planner's view.

3. **Treat scope as negotiable, not fixed.** When writing a detailed plan, actively consider:
   - **Refinements** — a deliverable that was vague at contract time has gotten clearer; rewrite it.
   - **Gaps** — something the contract assumed but didn't spell out (e.g. a missing test fixture, a config knob).
   - **Deferrals** — a deliverable that was scoped here but, on reflection, belongs in a later phase or [`inspector-deferred.md`](../inspector-deferred.md).
   - **Reorderings** — within a phase, which deliverable lands first changes risk profile (e.g. land the resolver before the new services that use it).
   - **Merges** — two adjacent phases whose work is genuinely coupled (e.g. Phase 5 publish + Phase 6 dashboard panel for publish jobs) might be cleaner together.
   - **Splits** — one phase whose deliverables don't all need to land at once (e.g. Phase 4 admin actions = just one of {force-release, reassign, force-set-state, send-back} could ship first as a vertical slice).

   When you propose a refinement/deferral/reordering/merge/split, **update this folder first** (the contract), then write the plan against the updated contract. Don't let the plan and the contract drift apart.

4. **Re-read the relevant detailed docs first.** Before the plan starts, the writer should read the parts of `inspector-deployment-plan.md`, `inspector-data-storage.md`, etc. that the phase touches. Doc agents may have edited them; cached mental models go stale. The phase docs cross-link the right sections.

5. **Test the plan against a fresh reader.** Once the detailed plan is written, sanity-check it the way doc-coauthoring suggests: spawn a fresh agent with **only the plan + the phase contract** (no conversation context) and ask "what would you build first? what's unclear? what would you ask before starting?" — then patch the gaps.

If the writer hits a question this folder can't answer, escalate: ask the human owner. Better to pause and confirm than guess and rebuild.
