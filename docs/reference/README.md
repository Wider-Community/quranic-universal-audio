# Inspector reference docs

Agent-facing technical reference for the **Inspector** (`inspector/`). Open the doc matching the subsystem you're working on. All docs are written for AI coding agents: terse, table-first, file-path-anchored, present-tense (what IS, not what's planned). When a doc and the code disagree, the code wins — fix the doc.

Everything here is inspector-related (flat, no nesting). Two subsystems are owned by **skills**, not by a reference doc here — those skills are the ground truth for their domain:
- **Audio** (peaks, proxy/clip/metadata routes, VBR/Xing, AudioPort/kill-switch, the extraction→intake handoff) → `inspector-audio` skill (`.claude/skills/inspector-audio/`).
- **Performance** (the cost model, cache inventory, hot-path costs, profiling + runtime-probing playbook) → `inspector-performance` skill (`.claude/skills/inspector-performance/`).

Where a reference doc here touches those domains (e.g. the route map in `architecture.md`, the playback stores in `frontend.md`, the cache invalidation rule in `architecture.md`), it stays a thin pointer — the skill holds the depth. Skills cover *how to work* (probes, workflows, conventions, anti-patterns) + the depth for their owned domain; the rest of this folder is the *what-is* for every other subsystem. Don't restate one in the other.

| Doc | Read when working on |
|---|---|
| [architecture.md](architecture.md) | **Start here.** Backend layering, `services/` + `routes/` subpackage map, domain/adapters/utils, caching, app.py boot, Quran Foundation integration. |
| [database.md](database.md) | The SQLite substrate (`inspector.db`) — connection/txn/WAL, repos, migrations, bucket sync + db_seq CAS. Source of truth for state/catalog/access/audit/activity/claims/requests. |
| [state-machine.md](state-machine.md) | Reciter lifecycle states, flags, transition matrix, events, `services/state/state.py`. |
| [auth-permissions.md](auth-permissions.md) | HF OAuth identity, roles, permission predicates, edit-lock, CSRF, admin endpoints, audit actor, activity rails. |
| [notifications.md](notifications.md) | Per-user "My Notifications" Dashboard rail — materialized `notifications` table, the `services/notifications` emitter (lifecycle + intake + segment-flag-reply), event→target resolver, dismiss/archive, `/api/me/notifications`. |
| [capabilities.md](capabilities.md) | The data-driven capability system (owner-configurable permission matrix) — the resolver `can()`, override store, the Permissions tab, and **the convention for adding a gate so it surfaces in the UI**. |
| [admin-dashboard.md](admin-dashboard.md) | Owner/maintainer admin modal — Users compartment (list + detail drawer), owner-only role picker, `/api/admin/*` endpoints. |
| [catalog.md](catalog.md) | Reciter catalog (now SQLite `repo_catalog`) — layers, slug convention, audio manifests, naming guide, maintenance. |
| [audio-metadata-pipeline.md](audio-metadata-pipeline.md) | How per-chapter audio metadata + delivery rollups are generated (offline extraction → intake mint), served, audited, and backfilled. VBR/phantom-tail caveats, source-probe pitfalls (ID3v2 tags, archive.org stale node urls, throttling), bucket/mount mechanics, the diagnostics+backfills tooling, and the runbook for onboarding a new source/channel or re-auditing the catalog. |
| [segments-editor.md](segments-editor.md) | Segments tab editor — command grammar, normalized state, identity, save flow, edit_history, undo, history view. |
| [timestamps-job.md](timestamps-job.md) | Timestamps subsystem — temporal segment-array `.json.gz` shard format (raw segments, byte pass-through read), consumer-side completion-based dedup, owner preview, the one-off reshape migration, the admin-triggered HF generation job (prebuilt public job image → in-container MFA, alignment-only → per-reciter `reciters/<slug>/jobs/ts/<id>.json` records), and the verse-level `ts_validation.json` accordion. |
| [dataset-and-releases.md](dataset-and-releases.md) | Dataset releasing model — bucket-as-canonical + three adapter projections (HF dataset, GH release tiers, future API), publish state model (`releases` SQLite table, three independent artifact tracks per reciter), eligibility, schema, failed/delete handling, parity invariants. |
| [automation.md](automation.md) | Owner-configurable release automations — the opt-in reconciler daemon that fires the release jobs on a schedule/rules (auto-gen TS, GH cut, HF batch-publish, stale-TS regen, stale-metadata refresh), config blob + state tables, the `release.manage_automation` gate, the Releases-tab Automation card, single-flight / failed-skip / debounce / chaining invariants. |
| [validation.md](validation.md) | Registry-backed validation engine, categories, persisted classifier fields, bench/drift harness. |
| [frontend.md](frontend.md) | The Svelte 5 SPA — dashboard/timestamps/segments tabs, `lib/` cross-tab, stores, charts, peaks caching. |
| [accordion-guides.md](accordion-guides.md) | Validation accordion help-modal guide templates (`tabs/segments/guides/`). |
| [config-deploy.md](config-deploy.md) | Env vars, Space secrets, image build, deploy workflow, healthz, single-worker invariant. |
| [data-migrations.md](data-migrations.md) | One-shot migration / backfill scripts (`scripts/migrations/`, `scripts/backfills/`) — detection, apply CLI, rollback. |
| [api-roadmap.md](api-roadmap.md) | **Roadmap / vision (not built yet).** The planned public data API — typed pip/npm SDKs over static CDN-hosted data + an optional HF-Space compute layer; the why, the caching/versioning model, and the build sequence. |
| [testing.md](testing.md) | Test suites — pytest (BE + qua_shared) and vitest (FE), conftest fixtures (`signed_in_client`, `tmp_reciter_dir`, `seed_state`, `state_persistence`), mocking boundaries, schema-parity policy, coverage, phase-gates. |

Audio: see `.claude/skills/inspector-audio/` (peaks, audio proxy/source, bucket audio/peaks read-only, VBR/Xing, probes).

Planning / rationale (the *why*) lives in `docs/planning/` and `docs/proposals/` (gitignored). This dir is the *what-is* contract.
