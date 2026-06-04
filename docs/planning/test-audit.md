# Test audit — repo-wide

## Executive summary

**Headline counts.** 745 confirmed findings across 64 subsystems. By category: 355 coverage gaps, 76 correctness defects in tests, 68 dead/legacy tests, 56 convention drifts, 38 fixture-promotion candidates, 31 onboarding items, 24 surfaced bugs in code-under-test, 21 isolation issues, 21 stale skip/xfail gates, 14 naming issues, 13 mocking-boundary issues, 12 codegen-parity gaps, 10 coverage-infra items, 4 parametrize improvements, 2 CI items. By severity: 5 critical, 106 high, 267 medium, 367 low.

**Top 12 highest-impact findings.**

1. **[critical, surfaced-bug]** `fuzzy-match.ts` Arabic regex strips base Arabic letters — every Arabic search across the picker, segments-tab labels, timestamps footer and dashboard combination-picker silently reduces input to `""`, returning everything or nothing. `inspector/frontend/src/lib/utils/fuzzy-match.ts:24`.
2. **[critical, correctness]** All `normalizeArabic` tests pass for the wrong reason — both sides of every assertion normalize to `""`, hiding (1) above. `inspector/frontend/src/lib/utils/__tests__/fuzzy-match.test.ts:7-39`.
3. **[critical, gap]** `playback.ts` (the main-list segment playback path) has zero direct tests — playFromSegment, ensureBoundedRange, _maybeSkipDeletedGap, onSegTimeUpdate, drawActivePlayhead, reconcilePlayingAfterMutation are entirely uncovered. `inspector/frontend/src/tabs/segments/utils/playback/playback.ts:303-732`.
4. **[critical, gap]** `ValidationPanel.svelte` (909 lines: virtualization, accordion-pin, warmup, filtering) has zero tests. `inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte:1-909`.
5. **[critical, gap]** `GET /api/seg/segment-clip` has no tests — the VBR transport, fail-loud invariant flagged in MEMORY.md, and the `_is_known_chapter_url` 403 open-proxy guard are unprotected. `inspector/routes/audio/clip.py:44-148`.
6. **[high, surfaced-bug]** `BucketBackend.list_dir` / `.exists` swallow every non-404 exception and return `False`/`[]` — HF 5xx, auth errors and throttling are silently rendered as "doesn't exist", masking real outages as missing-data. `inspector/services/storage/hf_bucket.py:511-535`.
7. **[high, surfaced-bug]** `_segFromSnapshot` does not copy `is_wasl` — discarding a `setIsWasl` op leaves the segment with the post-op value, silently dropping the revert. `inspector/frontend/src/tabs/segments/domain/inverse-patch.ts:29-47`.
8. **[high, surfaced-bug]** `_FFMPEG_TIMEOUT=600` in `qua_shared/peaks_compute.py:33` has silently drifted to twice the canonical `FFMPEG_FULL_TIMEOUT=300` in `inspector/config.py:97`; the parity test does not cover the constant.
9. **[high, gap]** `compute_audio_peaks` and `_bucket_pcm_minmax` in the vendored peaks copy have zero parity tests despite the module's docstring claiming byte-identical mirror — only `pack_slim` is checked. `qua_shared/peaks_compute.py:41-97` vs `inspector/tests/persistence/test_peaks_history_schema.py`.
10. **[high, gap]** Hand-rolled `_validate_record` in `services/audio/peaks_history.py:55-81` and `PeaksRecord.model_validate` in `qua_shared/schemas/peaks_history.py:44-90` have no parity test — writer-side validation can silently diverge from canonical reader. `inspector/services/audio/peaks_history.py:121`.
11. **[high, correctness]** `test_repo_transitions.py` — `test_requested_rejects_when_pending_exists` only trips the AWAITING_ALIGNMENT precondition; the pending-exists guard is wholly untested. `inspector/tests/services/test_state_request_events.py:227-246`.
12. **[high, correctness]** Five baseline-shape route tests assert `status_code in (200, 404)` then run the field-superset check only when 200 — a fixture-install regression goes silent. `inspector/tests/routes/test_route_validate.py:17-24`, `test_route_data.py:17-50`, `test_route_history.py:22-29`.

**What this PR contains vs. what follow-ups pick up.** This PR is **audit-only** plus coverage-infrastructure wiring. Concretely:

- The audit doc itself (this file).
- Pytest-cov flags + Vitest v8 coverage provider wired into CI (read-only — no thresholds, no failing-gate).
- A CI summary emission of headline numbers.
- An exclusion list for generated and intentionally-legacy files.

**Follow-up PRs:**

1. **Corrections PR** — applies all category=correctness / convention / dead-test / fixture / isolation / mocking / naming / parametrize / skip-xfail / coverage-infra / ci fixes (sections 3–7 below). No new tests, no new behavior.
2. **`docs/reference/testing.md`** — written from the outline in section 11.
3. **Gap-filling PR(s)** — write the missing tests (categories gap, codegen-parity, onboarding) following the prioritized plan in section 10.

---

## Surfaced bugs (in code-under-test — logged for triage)

These are real production defects discovered while auditing. **Not fixed in this PR.** Each is a separate cherry-pick candidate.

### Critical

**[critical] `ARABIC_DIACRITICS` regex strips base Arabic letters.** `inspector/frontend/src/lib/utils/fuzzy-match.ts:24` — the single-line class `[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ]` includes ranges `ؐ-ً` (U+0610–U+064B) and `ؚ-ٰ` (U+061A–U+0670), each engulfing every common base Arabic letter (U+0620–U+064A). Effect: `normalizeArabic('مَكْتَبَة')`, `normalizeArabic('أحمد')`, `normalizeArabic('الفاتحة')` all reduce to `""`. Every Arabic substring match in `SearchableSelect`, `CombinationPicker`, `CatalogList`, `StepReciter`, `TimestampsFooterLeft` returns either everything (if needle also collapses) or nothing. Diverges from the BE twin in `inspector/services/activity/search_normalize.py:20` whose multi-line class is correctly bracketed. **No existing test catches it** — see section 3 for why the FE tests pass tautologically. **Fix sketch:** replace with `inspector/frontend/src/lib/utils/arabic-text.ts:11`'s `TASHKEEL` constant, or rewrite as separate ranges mirroring the BE.

### High

**[high] `BucketBackend.list_dir` / `.exists` silently mask transient failures.** `inspector/services/storage/hf_bucket.py:511-515, 531-535` — both catch bare `Exception`, log a warning, return `False`/`[]`. A 5xx, auth error, throttling, or stuck mount becomes "file doesn't exist" to the caller. `FilesystemBackend` never raises HTTP errors so the interface contract is silently asymmetric. `read_bytes()` does re-raise non-404 errors, making the inconsistency a footgun. **No test pins the suppression behavior.** **Fix sketch:** raise on non-404 errors (preferred — matches `read_bytes`), or wrap exceptions in a dedicated `BucketTransientError` so callers can distinguish.

**[high] `_FFMPEG_TIMEOUT` drift in vendored peaks pipeline.** `qua_shared/peaks_compute.py:33` hardcodes 600s; canonical `inspector/config.py:97` defines `FFMPEG_FULL_TIMEOUT = 300`; canonical reader uses 300s at `inspector/services/audio/peaks.py:90`. The parity test in `qua_shared/tests/test_peaks_compute.py:46-55` enumerates other inlined constants but skips this one because it's private. The HF Job hangs for up to 5 extra minutes on stuck ffmpeg the Inspector kills. **No test catches.** **Fix sketch:** inline `FFMPEG_FULL_TIMEOUT` from `inspector/config.py` and extend `test_constants_match_config` to assert it. If the longer timeout is intentional, name and document it.

**[high] `_segFromSnapshot` silently drops `is_wasl` on inverse-apply.** `inspector/frontend/src/tabs/segments/domain/inverse-patch.ts:29-47` whitelists 11 segment fields when reconstructing from a snapshot but omits `is_wasl`. `snapshotSeg` (`stores/dirty.ts:108`) writes `is_wasl` when truthy; `_reduceSetIsWasl` (`domain/apply-command.ts:577`) captures `is_wasl` in the before-snapshot. Discarding a `setIsWasl` op restores a segment whose `is_wasl` is `undefined`, treated as `false` (`setIsWaslOnSegment` line 34: `=== true`). **No test exists.** **Fix sketch:** add `if (typeof snap.is_wasl === 'boolean') seg.is_wasl = snap.is_wasl;` to `_segFromSnapshot` and audit `snapshotSeg` for any other fields not mirrored back. Add a regression test that round-trips `setIsWasl` through forward+inverse and asserts `is_wasl` is restored.

**[high] Save handler injects empty `patch` envelope on every op missing one — undo becomes no-op.** `inspector/services/segments/save.py:124-156` (`_ensure_patch_on_ops`) writes `{before:[], after:[], removedIds:[], insertedIds:[], affectedChapterIds:[]}` onto any op without one. `apply_reverse_op` (`inspector/services/segments/undo.py:244`) routes any op carrying `patch` through `_reverse_via_patch`, which now sees the empty patch and does nothing. The fallback `op_type`-dispatched branches (`_reverse_trim`, `_reverse_split`, etc.) are unreachable for these ops. Save acceptance allows ops with discriminated `type` but no `patch`. Net effect: any op saved by a client that doesn't supply a patch is silently un-undoable. **Fix sketch:** hard-reject ops with `type` but no `patch` at the save boundary (mirror the command-envelope rejection), or gate `_ensure_patch_on_ops` to inject only when `op_type` and `type` are both absent (so legacy field-restore undo still runs).

**[high] `routes/admin/releases.py:128` and `:131` join `channels` twice with different aliases.** Functionally harmless (SQLite collapses) but wasteful. Surfaced while auditing `test_release_preview_uses_display_names`. **Fix sketch:** drop the second `JOIN channels ch ON ch.slug = d.channel` and change `ch.name AS channel` to `c.name`.

**[high] `repo_access.resolve_role` returns raw `str` for members but `Role.CONTRIBUTOR` for non-members despite `-> Role` annotation.** `inspector/services/db/repo_access.py:79-91`. Tests pass because `Role` is a str-enum, but `isinstance(x, Role)` and `.value` access behave inconsistently. Multiple production sites use `hasattr(x, "value")` defenses (`inspector/services/auth/access.py:193`, `inspector/routes/auth/auth.py:243`, `inspector/routes/segments/edit.py:29`) — confirming the hazard was felt. **Fix sketch:** wrap the member branch in `Role(row[0])` and remove the defensive `hasattr` checks downstream.

**[high] `_validation_engine.maybe_touch_entry` returns True + opens a `durable_transaction()` for absent users.** `inspector/services/admin/visitors.py:47-64`. `touch_last_entry` is UPDATE-only; for an unseen user the UPDATE affects 0 rows but `durable_transaction()` still bumps db_seq and triggers a bucket upload on commit. Every `/api/me` request from a pre-feature signed-in user pays one full-file DB upload until they re-login. **Fix sketch:** add a cheap SELECT-first guard or convert to INSERT-OR-IGNORE so absent users don't trigger a no-op write.

### Medium

**[medium] `routes/public/public.py:38-45` accepts `bucket=publishing` but no reciter can have that bucket.** The `PublicBucket` Literal at `inspector/services/reference/public_state.py:38-44` and `_STATE_TO_BUCKET` at `:62-68` list only five buckets. `?bucket=publishing` returns 200 with an empty list instead of 400. Stale literal from a removed pipeline stage. **Fix sketch:** drop `"publishing"` from `_VALID_BUCKETS` and rename `test_stats_returns_six_bucket_counts` to match.

**[medium] `_dispatch_to_terminal_handlers` swallows orchestrator exceptions on three webhook 502 paths and leaks raw `str(exc)` to the caller.** `inspector/routes/webhooks/ts_jobs.py:71-73, 121, 161-162`; same pattern at `inspector/routes/admin/reviews.py:140, 188, 206` and `inspector/routes/admin/releases.py:92, 298`. **Fix sketch:** convert envelopes to `{error: 'upstream', code: 'UPSTREAM_FAILED'}` and log details at warning. Add 502 to FE `STATUS_FALLBACK`.

**[medium] `set_role()` returns three inconsistent response shapes.** `inspector/services/admin/users.py:60-98`: `{ok, role, noop}` on no-op, `{ok, role}` on demote, `{ok, member}` on grant/update. FE client wouldn't crash today (early-return guard) but the wire-shape inconsistency is a footgun for any programmatic consumer.

**[medium] `_neutralise()` does not escape `&` — pre-encoded HTML entities pass through.** `qua_shared/release_changelog.py:31-34`. A `&lt;script&gt;...` in `operator_note` renders as live markup on GitHub. operator_note is untrusted free text per the module docstring. **Fix:** `s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')`.

**[medium] `parseSegRef` silently drops the end-side surah.** `inspector/frontend/src/tabs/segments/utils/data/references.ts:32-40`. `'1:1:1-2:1:1'` parses as if both endpoints share surah 1; `_validateRefStructural` and `_clampRefWordOvershoot` cannot detect a cross-surah malformed input. The docstring at `:108-110` explicitly says segments never cross surahs. **Fix:** extend `ParsedSegRef` with `surah_from`/`surah_to` and have `_validateRefStructural` reject when they differ.

**[medium] `_sameSource` ignores `cbrSrc`.** `inspector/frontend/src/lib/playback/audio-port.ts:262-267` compares only `audioUrl + reciter + vbr`. Updating `cbrSrc` (e.g. swapping canonical CDN URL for an audio-proxy wrap) silently no-ops; the next `loadCovering` uses the stale desiredUrl. **Fix:** `(a.cbrSrc ?? a.audioUrl) === (b.cbrSrc ?? b.audioUrl)` in the comparison.

### Low

- **[low] CLAUDE.md says schemas use `ConfigDict(extra='allow')` for forward-compat — but persistence schemas use `extra='forbid'` + `strip_and_warn` (opposite behavior).** `CLAUDE.md:120` vs `qua_shared/schemas/edit_history.py:75,116`, `peaks_history.py:65`, `segment.py:97+`, `catalog.py:308-336`, `qua_shared/schemas/_extras.py:1`. Misleads contributors into assuming unknown future fields survive read-then-rewrite.
- **[low] `_chapter_loopback` test fixture is named for a "loopback" but actually carries three segments (1:1×2 + 1:2).** `qua_shared/tests/test_timestamps_reshape.py:63-80`, `test_timestamps_segment_shards.py:64-82`. Misleading name.
- **[low] Stale docstring at `inspector/services/audio/peaks_history.py:181-184` points at non-existent `services.history_query.parse_history_file` — actual function is `services.activity.history_query.parse_history_for_reciter:61`.
- **[low] `_FakeBackend.read_bytes` in `inspector/tests/services/test_reference_resource_bytes.py:23-27` raises `FileNotFoundError`, but real backends raise `StorageNotFound`.** Tests pass because `static_refs.load_qpc_bytes` catches broad `Exception`. Narrowing the except clause to `StorageNotFound` later would silently pass these tests but blow up in production.
- **[low] Audio proxy stub mocks only the BytesIO branch.** `inspector/tests/routes/test_route_audio_proxy.py:9-35` mocks `audio_source.resolve` to a `BytesIO` source on all four tests; the `path` branch (send_file with ETag) and the `_stream_cdn` branch (Range forwarding, ACAO, 502 on RequestException) are unverified. Bug-by-omission risk in CORS / Range handling.
- **[low] `time_start`/`time_end` ge=0 constraints in `qua_shared/schemas/peaks_history.py:69-70` are loosely tested.** Existing inverted-range test would also pass under negative values that happen to be ordered (e.g. `start=-10, end=-5`). Surface: a regression dropping ge=0 from the field would not be caught.

---

## Correctness fixes (for the corrections PR)

Test assertions that pass for the wrong reason, name/intent mismatches, and tautological assertions. Grouped by subsystem.

### Tests that pass tautologically or for the wrong reason

**Arabic / search-normalize.**

- `inspector/frontend/src/lib/utils/__tests__/fuzzy-match.test.ts:7-39` — every `normalizeArabic` assertion has both sides collapse to `""`; the `match()` test passes via `''.includes('')`. Strengthen each to assert against an expected canonical form (`expect(normalizeArabic('مَكْتَبَة')).toBe('مكتبه')`) and add a negative assertion so the all-collapse-to-empty mode cannot recur.

**State machine.**

- `inspector/tests/services/test_state_request_events.py:227-246` `test_requested_rejects_when_pending_exists` — claims to test the pending-exists guard but the InvalidTransition is raised by the AWAITING_ALIGNMENT state-precondition; the test's own comment admits the mismatch. Either reshape to truly hit the pending-exists branch (force the row back to CATALOGUED leaving the pending row alive, then re-fire), or rename and split off a focused test for the pending-check branch.
- `inspector/tests/services/test_state_request_events.py:131-621` and `inspector/tests/services/test_activity_state.py:74-101`, `test_catalog_edit_delivery.py:88-136`, `test_pending_requests.py:205-284`, `test_route_requests.py:107`, `test_route_public_activity_delete.py:37` — **30+ tests stub `services.audit.append` to a no-op `lambda *a, **kw: None`**, then only assert post-transition state. Audit emission is the durability boundary; the stub guarantees the test cannot catch a regression that drops `audit.append` from the handler. Replace with a recorder-or-real implementation and assert against `repo_transitions.for_slug(slug)`.

**Detailed-schema / Pydantic round-trips.**

- `inspector/tests/persistence/test_detailed_schema.py:96-110` — `test_detailed_json_additive_only_classified_issues_optional` is named for "additive optional" but asserts the strict negative `'classified_issues' not in seg`. Rename to `test_detailed_json_excludes_classified_issues`.
- `inspector/tests/persistence/test_detailed_schema.py:85-93` — `test_detailed_json_no_field_removed` asserts only fixture-keys-subset-of-allowlist; the contract claimed by the name (no removed field) is not enforced. Rename to `test_fixture_segments_use_only_known_keys` and add a complementary assertion that every required `DetailedSegment` field is present in at least one fixture seg.
- `inspector/tests/persistence/test_detailed_schema.py:16-35` — `KNOWN_SEGMENT_FIELDS` allow-set omits `is_wasl` (declared field in `qua_shared/schemas/segment.py:121`, persisted by `inspector/adapters/save_payload.py:93-97`). Add `is_wasl`, and consider auto-deriving the set from `set(DetailedSegment.model_fields)` + explicit legacy tolerance keys.

**State / repo regression-coverage gaps.**

- `inspector/tests/db/test_repo_state.py:61-73` `test_release_clears_assignee` — asserts only that the assembled `assignee_hf_id is None`, which holds purely because the read-time gate in `_assemble` (`repo_state.py:60`) only fills assignee_* when state == UNDER_REVIEW. The actual call (`close_claim`) is not verified. Add `assert repo_claims.get_open_claim('d1') is None`.
- `inspector/tests/routes/test_state_parity.py:234-258` `test_anonymous_sees_redacted_assignee_consistently` — asserts absence of `assignee_hf_id` from `_to_public_delivery` payload which is never present under any condition. Drive from both anonymous and authenticated maintainer; assert equivalent payloads instead.
- `inspector/tests/routes/test_state_parity.py:194-200` — `_ok` validate-stub returns 5 of 6 `BLOCKING_COUNT_KEYS`, omitting `repetitions`. Passes via `dict.get(k, 0)` coincidence; the gate for `repetitions` is never exercised. Duplicated stub at `test_route_claims.py:393-465`.
- `inspector/tests/routes/test_route_validate.py:17-24`, `test_route_data.py:17-50`, `test_route_history.py:22-29` — five baseline-shape tests accept `status_code in (200, 404)`. A fixture-install regression returns 404; the shape check sits behind `if res.status_code == 200`. Replace with hard `== 200` assertion; rely on dedicated 404 tests for that path.
- `inspector/tests/routes/test_route_undo.py:30-106`, `test_route_save.py:101-255`, `inspector/tests/undo/test_patch_undo.py:155` — loose status tuples (`in (200, 400, 404)`) mask which branch was tested. Replace each tuple with the specific expected status; for "gate passed, payload-shape may complain" assertions use `assert res.status_code != 403`.

**Peaks / audio routes.**

- `inspector/tests/routes/test_route_peaks.py:102-111` `test_peaks_response_cache_returns_same_body_on_repeat` — only asserts byte-equality of two identical requests, which holds regardless of cache hit. After the first request, monkeypatch `audio_fetch.read_prefetched_peaks` to raise, or assert `get_peaks_response_cache(reciter, (112,)) is not None`.
- `inspector/tests/routes/test_route_peaks.py:155-179` `test_peaks_no_lock_deadlock_on_misses` — docstring says "installs slim peaks across two chapters" but the test installs only chapter 112. A single-chapter request can't reproduce a non-reentrant deadlock. Install slim peaks for ≥2 chapters and request all of them, or replace the wall-clock budget with `@pytest.mark.timeout(2.0)`.
- `inspector/tests/routes/test_route_peaks.py:165-171` — docstring/code mismatch ("two chapters" vs one chapter in the test body).

**Capabilities / state-machine bridge.**

- `inspector/tests/services/test_capabilities.py:132-159` `test_event_capability_map_is_complete_and_valid` — equality-snapshot against a 16-entry literal. The intent (un-gating regression) is one direction only; equality also fails on additive PRs. Replace with directional check + an allow-list of legitimately non-gated events.
- `inspector/tests/services/test_capabilities.py:124-129` `test_registry_self_consistency` — duplicates a module-level assert (`qua_shared/schemas/capabilities.py:398`); the duplicate assertion (every default_grants tier is real) is enforced by Pydantic at construction. Delete or repurpose.

**Validation registry.**

- `inspector/tests/registry/test_registry_extensibility.py:16-50` `test_synthetic_new_category_picked_up_by_parametrization` — claims parametrized behavior tests auto-cover a synthetic category, but pytest parametrization is collection-time; runtime monkeypatching never feeds the new category into them. Rename or call the parametrized targets directly with the augmented set.
- `inspector/tests/classifier/test_classify_per_category.py:105-112` `test_boundary_adj_phoneme_tail_optional` — asserts `"boundary_adj" in plain or "boundary_adj" not in plain` (always True). The phonemic side of boundary_adj has been retired (`classifier.py:130`). Delete or repurpose for the structural-only path.

**Segments / save / undo.**

- `inspector/tests/routes/test_route_save.py:265-291` `test_save_includes_patch_field_in_history` — sends a `delete` op with `command.segmentUid` + `full_replace: true, segments: []`; the route accepts (200), wipes all segments, stamps an empty patch. The test only verifies that `patch` is present. The op's stated target is never matched against the (now empty) segments; an undo cannot restore. Validate delete ops against in-payload segments at save time.

**Snapshot regenerators / parity.**

- `inspector/tests/parity/snapshot_route_baselines.py:78-88` — patches `RECITATION_SEGMENTS_PATH` on 5 of 7 modules that don't expose it. Only `services.activity.history_query` and `services.storage.data_loader` still define it. The other 5 (`routes.segments.{data,edit,validation}`, `services.segments.save`, `services.segments.undo`) go through `services/storage/data_dir.py`; the `hasattr(...)` guard silently skips them. Rewrite to install a `FilesystemBackend` rooted at the tmp dir + `INSPECTOR_BACKEND=filesystem`, mirroring `conftest.py:420`.
- `inspector/tests/parity/snapshot_route_baselines.py:61` — sets `os.environ['INSPECTOR_DATA_DIR']` in the parent process without restoring. Pass via subprocess `env=` instead, or save/restore in a try/finally.

**Recitation parser.**

- `inspector/frontend/src/tabs/segments/__tests__/parity/classifier-output.test.ts:18-21` — asserts `expect(historyItems!.usesStoredClassifiedIssues).toBe(true)` against a hardcoded `export const usesStoredClassifiedIssues = true`. Replace with a real guard against any live-classifier export (e.g. assert `_classifySegCategories` is not exported from a `live-classifier` path).

**Stores / segments FE.**

- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/selectors.test.ts:46-52` `selectors return new array references on state change` — `getChapterSegments` allocates a fresh array on every call; the assertion passes regardless of state change. Rewrite to subscribe + count notifications, or rename to "returns fresh arrays per call".
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/compat.test.ts:16-23` — `_byChapter` is never present under any condition; `snapshot?._byChapter === undefined` for null `snapshot`. The assertion guards nothing. Either populate `segAllData` first or drop.
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/compat.test.ts:11,16,25` — `it()` names ("has same shape as before refactor", "existing components subscribe without modification") promise shape preservation; bodies only assert `typeof X.subscribe === 'function'` which is true for any writable. Rename or strengthen.
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/uid-backfill.test.ts:9-24` `frontend loader backfills uid for legacy fixture` — discards the `legacySeg` and calls `deriveUid` directly; `backfillSegmentUids` is never invoked. Rename or call `backfillSegmentUids([legacySeg(1, 0, 0)], 1)`.

**Validation / identity FE.**

- `inspector/frontend/src/tabs/segments/__tests__/identity/resolve-issue.test.ts:54-62` `uses segment_uid first when present` — seeds one segment matching by both uid and seg_index; cannot distinguish uid-first from seg_index-first. Seed two segments, one matching by uid only, one by seg_index only, and assert the uid-matched one is returned.
- `inspector/frontend/src/tabs/segments/__tests__/identity/resolve-issue.test.ts:86-88` `matches errors-category by verse-key prefix` — body only asserts `typeof resolve.resolveIssueSeg === 'function'`. Delete or replace with an actual prefix-match call.

**Segment registry / parity.**

- `inspector/frontend/src/tabs/segments/__tests__/registry/parity.test.ts:14-39` — `PY_SNAPSHOT` is a TS literal copy of the Python policy matrix; cross-language symmetry is asserted against a duplicated literal. Codegen the snapshot from `registry_as_dict()`, or have the FE parity test read a JSON snapshot emitted by a BE pytest fixture.
- `inspector/frontend/src/tabs/segments/__tests__/registry/parity.test.ts:14-28` + `policy.test.ts:14-28` — same 13-row matrix duplicated byte-for-byte. Extract.
- Real drift exists today: `inspector/services/validation/registry.py:143,179` (Python) vs `inspector/frontend/src/tabs/segments/domain/registry.ts:114,150` (TS) differ on `repetitions.description` and `cross_verse.description`; the parity test misses it because it doesn't compare `description`.

**Mark-ready parity.**

- `inspector/frontend/src/tabs/segments/__tests__/parity/mark-ready-copy.test.ts:3-9, 75-83` — leading comment says "five checklist keys" but the suite asserts six. Same stale "five" comment in `qua_shared/schemas/mark_ready.py:9`.

**Audio-range port.**

- `inspector/frontend/src/lib/playback/__tests__/audio-range-port.test.ts:101-109` — `setFileTime` helper has dead arithmetic `(offset + fileMs - offset) / 1000` and the docstring claims VBR "subtracts the offset". Math is identity; parameter is clip-relative not file-absolute. Rename `setClipTimeMs`, drop the dead arithmetic, fix the docstring.
- `inspector/frontend/src/lib/playback/__tests__/audio-range-port.test.ts:356-370`, `audio-range.test.ts:446-468` — `cancels pending advance timer` tests never advance past the range boundary before `dispose()`, so no advance timer was ever scheduled. The subsequent `vi.advanceTimersByTime(10_000)` trivially shows `audio.play` wasn't called.

**Audio graph.**

- `inspector/frontend/src/lib/playback/__tests__/audio-graph.test.ts:129-140` `cutAudio/uncutAudio call ctx.resume() if the context is suspended` — `cutAudio` itself doesn't call resume; `getAudioGraph` does, then returns null, then `cutAudio` no-ops. Test passes for the wrong reason. Rename and add an assertion that `scheduled[]` is empty.

**Audio port.**

- `inspector/frontend/src/lib/playback/__tests__/audio-port.test.ts:285-290` `same source (re-set) is a no-op` — only checks `port.source` equality, not the no-op observable (no `_abortPendingLoad`, no `_window` clear). Add a `loadCovering` first; assert the second `setSource` does NOT clear `port.window` nor reload.

**Validation UI.**

- `inspector/frontend/src/tabs/segments/components/validation/__tests__/AccordionGuideModal.test.ts:41-52` `opens a code-stored text guide without fetching` — passes because the user is anonymous so `recordGuideRead` early-returns before `fetch`. Decouple by seeding a signed-in user.

**Visible-poll.**

- `inspector/frontend/src/lib/utils/__tests__/visible-poll.test.ts:90-107` `discards-after-hide` — never verifies the abort signal; the swallow happens via the resolve-time `!isVisible()` re-check. Capture the signal and assert `signal.aborted === true` after the hide.

**Goto-segments.**

- `inspector/frontend/src/lib/utils/__tests__/goto-segments.test.ts:27-31` `is a no-op for an empty slug` — never pre-seeds stores to a non-empty value; the assertion `expect(get(selectedReciter)).toBe('')` is the default. Pre-seed first.

**Public state-bucket.**

- `inspector/tests/db/test_public_state_bucket_dates.py:68` `afr == sorted(afr)` is a tautology on Windows where `datetime.now()` ties at ~15 ms granularity. Inject monotonically advancing timestamps or assert against `transitions.seq`.

**Bucket guard / static refs.**

- `inspector/tests/services/test_reference_resource_bytes.py:23-27` — `_FakeBackend.read_bytes` raises `FileNotFoundError`; real backends raise `StorageNotFound`. Tests pass only because `static_refs.load_qpc_bytes` catches broad `Exception`. Change the fake to raise `StorageNotFound`.

**Migration regression coverage.**

- `inspector/tests/admin/test_migration_0002.py:7-21` — only asserts post-migration shape on the fresh-chain DB; would pass if 0002 were inlined into 0001. Mirror the 0007 pattern: build a DB at user_version=1 with a minimal 0001 skeleton, run `migrate.run_migrations`, assert the columns/table/indexes are present.
- `inspector/tests/admin/test_migration_0010.py:7-24` — same gap (only asserts the post-state on fresh-chain DB).
- Migrations 0011, 0012, 0014, 0015 have no regression tests at all (`inspector/services/db/migrations/0011_drop_prefetch_purge_at.sql:1` through `0016_delivery_source_url.sql:1`).
- `inspector/services/db/repo_releases.py:60-78` — `test_supersede_current_marks_prior_rows` asserts `n == 0` because id1 was already superseded; the name promises the opposite. Capture and assert the first sweep's rowcount.

**Identity / phase tombstones.**

- `inspector/tests/identity/test_validation_identity.py:97-114` `test_no_index_fixups_after_phase_6` — walks `__file__` looking for a hardcoded worktree slug `inspiring-ramanujan-2d4e7e` that doesn't exist in the current worktree. The walk terminates at the drive root, `os.walk` finds zero files, the assertion passes trivially. Anchor relative to `Path(__file__).parents[N]` (3 parents up).

**Webhook / route 400-only assertions.** Many 4xx assertions check only status code and not body shape — see the broader convention drift in section 4 (`400-status-only-no-error-code`). Promote the canonical pattern `assert res.status_code == 400 and res.get_json()['code'] == '<EXPECTED_CODE>'` everywhere a `code` is expected, and cross-check codes against `friendly.ts` `CODE_COPY` keys.

### Tests that pass for coincidental reasons

- **Toggle/SearchableSelect aria-x missing.** `Toggle.test.ts:6-55` asserts events suppress but not `class:locked`/`class:on` rendering; `SearchableSelect` (909-line picker) has zero tests but the smoke test for `CombinationPicker` exercises only mouse clicks, leaving `aria-expanded`/`aria-activedescendant`/keyboard nav unverified — see section 11.
- **Modal focus trap untested.** `Modal.test.ts:38-46` covers Escape close, backdrop click, body scroll lock; the focus-trap (Tab/Shift-Tab cycling) and focus-return logic at `Modal.svelte:28-98` are not asserted.

---

## Convention realignment (for the corrections PR)

Convention drifts where the dominant pattern is clear and the divergent files should be brought into line.

### State-of-the-error envelope (BE)

**Convention.** Assert `res.status_code == 4xx and body['code'] == '<CODE>'`. Codes match the FE `CODE_COPY` table in `inspector/frontend/src/lib/errors/friendly.ts`.

**Divergent sites.** Tests that assert only the status code, missing the `code` envelope:
- `inspector/tests/routes/test_route_admin_actions.py:238, 277, 290, 367, 390, 449`
- `inspector/tests/routes/test_route_claims.py:235, 407`
- `inspector/tests/routes/test_route_public.py:252, 258, 263`
- `inspector/tests/routes/test_route_public_activity_delete.py:93`
- `inspector/tests/routes/test_route_requests.py:176, 189, 297, 351, 402, 419`
- `inspector/tests/routes/test_route_ts_webhook.py:115`

**Proposal.** Adopt `status + code + (where present) context` everywhere. Cross-check the asserted codes against `friendly.ts` `CODE_COPY` keys so FE/BE lockstep is mechanically verifiable.

### Inline `Origin` headers vs `_HEADERS`

**Convention.** Sibling route tests define `_HEADERS = {'Content-Type': 'application/json', 'Origin': _ORIGIN}` at module top and reuse on every POST.

**Divergent sites.** `inspector/tests/routes/test_route_claims.py` repeats `headers={'Origin': 'http://localhost'}` 23 times (lines 118-704); `test_route_save.py:22` and `test_route_requests.py:22` use the constant. **Proposal:** add `_HEADERS = {'Origin': 'http://localhost'}` near top of `test_route_claims.py` and replace inline dicts.

### `import { describe, expect,it }` spacing

**Divergent sites.** 21 FE test files import without space after comma; sibling tests (`save/discard-op-group.test.ts:7`, `save/inverse-patch.test.ts:7`) use the conventional spacing. Run `npm run lint --fix` on `__tests__/command/*.test.ts`, both save tests using the bad form, plus the others identified.

### Subdirectory layout for BE tests

**Convention.** `inspector/tests/<subsystem>/test_*.py` with established subdirs (`admin/`, `classifier/`, `command/`, `db/`, `identity/`, `persistence/`, `registry/`, `routes/`, `scripts/`, `services/`, `undo/`, `utils/`).

**Divergent files (19 at root that belong in subdirs).**
- `inspector/tests/test_audio_meta.py`, `test_audio_source.py`, `test_auto_split.py`, `test_peaks_bucketing.py`, `test_peaks_slim.py`, `test_peaks_vbr.py`, `test_quran_refs.py` → `tests/services/`
- `inspector/tests/test_bookmarks_routes.py`, `test_dev_mode.py`, `test_qf_content_audio.py`, `test_qf_content_wbw.py`, `test_static_catalog.py`, `test_static_quran_refs.py`, `test_ts_vbr.py` → `tests/routes/`
- `inspector/tests/test_utils_references.py` → `tests/utils/`
- `inspector/tests/test_capability_convention.py` → `tests/services/` (or `tests/conventions/`)
- `inspector/tests/test_app_smoke.py` — fine at root as cross-app smoke

**Proposal.** Move and add a sentence to `tests/README.md` (or conftest docstring): "one subdirectory per subsystem; cross-cutting smokes only at the root".

### Operational scripts disguised as tests

**Convention** (CLAUDE.md): operational CLIs go under `scripts/<function>/`; pytest tree contains test assertions.

**Divergent sites.**
- `inspector/tests/smoke/_bucket_smoke.py`, `_services_smoke.py`, `_storage_smoke.py` — underscored to skip pytest, intended to be run as scripts.
- `inspector/tests/parity/snapshot_expected_outputs.py`, `snapshot_route_baselines.py` — regenerator entrypoints named `snapshot_*.py` (not `test_*.py`).

**Proposal.** Move smoke scripts to `scripts/diagnostics/`; move regenerators to `scripts/codegen/regen_route_baselines.py` / `regen_classifier_baselines.py`. Update docstrings to point at the new paths. Leave a `tests/smoke/README.md` redirect.

### Stale phase narration in comments / docstrings

**Convention** (`.claude/rules/comments.md`): "no comments mentioning refactors / cleanups — `no longer`, `phase`, `removed`, `deleted`, `deprecated`, `legacy`, `old`, `new`, `will change/be` are red flags".

**Divergent sites (sample).**
- `inspector/routes/admin/access.py:3` — "Backend-only in Phase 3 — the admin dashboard UI lands in Phase 7" (UI landed weeks ago).
- `inspector/routes/admin/actions.py:3` — "Phase 4 backend surface".
- `inspector/tests/routes/test_route_save.py:1, 259, 296, 324` — `Phase 3 wired`, `Phase 5 contract`, `Phase 3: save handler validates`, `Phase 3 deliverable`.
- `inspector/tests/routes/test_route_undo.py:6`, `test_route_history.py:35, 60-66`, `test_route_admin_actions.py:1, 122, 293`, `test_route_claims.py:180-185`.
- `inspector/tests/command/test_apply_command.py:24-28, 64-70`; `test_command_per_op.py:36-42`; `test_auto_suppress.py:3-12`.
- `inspector/tests/parity/snapshot_expected_outputs.py:5, 11, 57` — "Pre-Phase-2 the script raises ImportError" (Phase 2 has shipped).
- `inspector/tests/classifier/test_classify_per_category.py:13`; `inspector/tests/identity/test_validation_identity.py:40, 55, 70, 83, 97`.
- `inspector/tests/registry/test_registry_extensibility.py:10`, `test_registry_behavior.py:11`, `test_registry_policy.py:10`.
- `inspector/tests/routes/test_route_data.py:56`.
- `inspector/tests/db/test_repo_requests_activity.py:98-99` — "were dropped with the admin notifications rail (migration 0006)".
- `inspector/tests/services/test_pending_requests.py:105-106` — tombstone for deleted test.
- `inspector/tests/routes/test_route_requests.py:106` — comment claims "Silence audit appends so tests don't write JSONL into tmp_path" but audit is now SQLite.
- `inspector/services/audio/peaks_history.py:1-9` — `Slice B of phase 6.`
- `inspector/frontend/src/tabs/segments/utils/playback/preview.test.ts:20-24` — "preview.ts now wraps CBR URLs ...".
- `inspector/frontend/src/tabs/segments/utils/playback/warmup.test.ts:70-73` — "Dropped — Chrome was deferring ...".
- `inspector/frontend/src/tabs/timestamps/services/ts_client.ts:1-11` — "The implementation moved to ...".

**Proposal.** Sweep `inspector/tests/**/*.py` + relevant production files for `phase-`/`Phase ` strings in skip reasons, docstrings, policy fields, and inline comments; rewrite to describe the structural invariant rather than the migration history.

### Local _seed_state / _row / _replace_state wrappers shadowing conftest

**Convention.** `inspector/tests/conftest.py` exposes `_seed_state`/`_seed_role`/`_seed_catalog`/`_seed_delivery_chain` callables and `seed_state`/`seed_role` fixtures.

**Divergent sites.**
- `inspector/tests/routes/test_route_claims.py:77-98` defines `_row` + `_replace_state`.
- `inspector/tests/routes/test_route_admin_actions.py:24-49` defines the same with slightly different defaults (`state='under_review'` vs `'awaiting_review'`).
- `inspector/tests/routes/test_route_access_admin.py:25-33` defines the same.
- `inspector/tests/routes/test_state_parity.py:21-55` defines `_state_row` returning a `ReciterRow` then destructures via `_seed_state(**kwargs)` — Pydantic validation per row for no reason.
- `inspector/tests/services/test_auto_detect.py:75-77` defines `_seed_state(backend, ...)` whose `backend` parameter is never used.

**Proposal.** Promote `_row(slug, **overrides) -> dict` and `seed_rows(*specs)` to `tests/conftest.py`. Drop the five copies. Drop the unused `backend` parameter in `test_auto_detect.py:75`.

### Local `_hf_user` / `_stub_hf_users` helpers

**Convention.** None — duplicated across two route test files because there's no shared conftest.

**Divergent sites.** `inspector/tests/routes/test_route_admin_actions.py:58-78` used by 8 tests in that file. **Proposal.** Promote to `tests/conftest.py` as `hf_user_factory` + `stub_hf_users` fixtures.

### `os.environ.setdefault('INSPECTOR_SESSION_SECRET', '0'*64)` at module-import time

**Convention.** `signed_in_client` fixture in `conftest.py:307-308` handles this via `monkeypatch.setenv`, designed to work even if the env var is unset. `app.py:251-256` gracefully handles a missing secret.

**Divergent sites.** 28 test files set the secret at module import. Examples: `inspector/tests/routes/test_route_claims.py:20`, `test_route_admin_actions.py:14`, `test_route_access_admin.py:20`, `test_route_intake_ingest.py:26`, `test_route_admin_releases.py:28`, `test_route_auth.py:24` (plus 22 more).

**Proposal.** Delete every module-level setdefault and rely on the fixture. If a route test must import the app at module load with no secret in env, set it once at `tests/conftest.py` module top. Document the import-order constraint in the conftest docstring.

### Function-scoped `get_conn` import

**Convention.** Module-level imports under `services.db`.

**Divergent site.** `inspector/tests/db/test_repo_releases.py:28` imports `get_conn` inside `_seed_minimal_delivery`. **Proposal.** Hoist.

### Function-local `from datetime import datetime, timezone`

**Convention.** Module-level when used at module scope.

**Divergent sites.** `inspector/tests/services/test_pending_requests_schema.py:65, 72` (already imported at line 8); `inspector/tests/routes/test_route_access_admin.py:169-173, 199-203, 226-230` (entire 4-line block of unused imports per test). **Proposal.** Delete the in-function imports.

### `loadOptional` dynamic import for FE modules that all ship

**Convention.** Static `import { X } from '../../path'` for modules that exist. `loadOptional()` exists only because Vite static-analysis refused to bundle dynamic imports whose target did not exist at config time.

**Stale callers.** All 15 deferred-block sites + 16 phase-gated suites under `__tests__/command/`, `__tests__/identity/`, `__tests__/normalized-state/`, `__tests__/registry/` (see section 5 for the comprehensive list).

**Proposal.** Convert to static imports; delete `__tests__/helpers/optional.ts`.

### `@vite-ignore` + `as any` cast everywhere

**Convention.** Typed command literals.

**Divergent sites.** Every `applyCommand(state, { ... } as any)` call in the 8 command-test files. **Proposal.** Drop `as any`; type as the appropriate discriminated-union member.

### `events: {...}` vs callback prop testing styles

Not a defect — but document the Svelte 4 vs Svelte 5 convention in `docs/reference/testing.md` (see section 11) so contributors copy-pasting from `Modal.test.ts` for a runes component don't get confused.

### qua_shared sys.path bootstrap

**Divergent sites.** Seven `qua_shared/tests/test_*.py` files inject `Path(__file__).resolve().parents[3]` (which points one level above the repo root). The injection is a no-op in CI (PYTHONPATH set in workflow), but masks the latent off-by-one bug. **Proposal.** Add `qua_shared/tests/conftest.py` with `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`, delete the seven per-file blocks and the noqa: E402 tax.

---

## Dead / legacy tests (for the corrections PR)

Tests that don't test what they claim, run vacuously, or are stale phase placeholders.

### Phase-gated deferred describe blocks (15 sites)

Every Phase-N `describe.skipIf(<truthy>)('... (deferred)', () => { it.todo('phase-X: <module> not yet present') })` block referenced below skips permanently because the gated module exists. The `it.todo`s are dead placeholders and the `loadOptional` indirection no longer earns its complexity.

- `inspector/frontend/src/tabs/segments/__tests__/registry/policy.test.ts:47-49`
- `inspector/frontend/src/tabs/segments/__tests__/registry/parity.test.ts:42-44`
- `inspector/frontend/src/tabs/segments/__tests__/registry/behavior.test.ts:65-67`
- `inspector/frontend/src/tabs/segments/__tests__/command/apply-command.test.ts:73-75`
- `inspector/frontend/src/tabs/segments/__tests__/command/trim.test.ts:79-81`
- `inspector/frontend/src/tabs/segments/__tests__/command/split.test.ts:242-244`
- `inspector/frontend/src/tabs/segments/__tests__/command/merge.test.ts:63-65`
- `inspector/frontend/src/tabs/segments/__tests__/command/delete.test.ts:60-62`
- `inspector/frontend/src/tabs/segments/__tests__/command/ignore.test.ts:64-66`
- `inspector/frontend/src/tabs/segments/__tests__/command/reference.test.ts:62-64`
- `inspector/frontend/src/tabs/segments/__tests__/command/auto-suppress.test.ts:93-95`
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/compat.test.ts:32-34`
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/uid-backfill.test.ts:38-40`
- `inspector/frontend/src/tabs/segments/__tests__/identity/stale-filter.test.ts:32-34`
- `inspector/frontend/src/tabs/segments/__tests__/identity/resolve-issue.test.ts:91-93`

**Action.** Delete every `(deferred)` block plus the `it.todo`, switch to static imports, drop `describe.skipIf(!mod)` outer gates, delete `__tests__/helpers/optional.ts` (and `__tests__/helpers/xfail.ts` which has zero callers — `helpers/xfail.ts:13`).

### Stale FE phase-1 throw guards inside it()

- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/compat.test.ts:12, 17, 26` — `if (!segmentsStore) throw new Error('phase-4: stores/segments not yet present')` is dead because the outer `describe.skipIf(!chapterStore)` already gates and both modules exist.

### Stale "no-op" stubs and helpers

- `_stub_state_persist` (`inspector/tests/routes/test_route_admin_actions.py:52-56`) and `_stub_access_persist` (`inspector/tests/routes/test_route_access_admin.py:44-52`) are documented no-ops post-cutover. Both files have ~30 call sites passing `monkeypatch` for no reason. Delete both helpers and all calls.
- `_clear_state` (`inspector/tests/routes/test_route_auth.py:41-44`) returns None; the autouse `_substrate_db` already gives each test a fresh DB. Delete and the 3 call sites.
- `_isolate_activity_state` (`inspector/tests/services/test_public_activity.py:14-18`) is an autouse fixture documented as a no-op post-cutover. Delete.
- `fresh_state` fixture (`inspector/tests/services/test_activity_state.py:16-32`) sets up `FilesystemBackend` + `hydrate()` that activity_state never uses; the docstring still says "FilesystemBackend so each test starts with a clean store" (it lives in SQLite). Strip to yield just the service.
- `fresh_archive` fixture (`inspector/tests/services/test_request_archive.py:16-32`) — same issue. All tests destructure `svc, _ = fresh_archive`.
- `fresh_pending` fixture (`inspector/tests/services/test_pending_requests.py:27-46`) — same: yields backend that pending_requests no longer touches.
- `seeded_catalog` fixture (`inspector/tests/services/test_pending_requests.py:170-174`) is a no-op wrapper around `fresh_pending` that takes `monkeypatch` and never uses it. Delete.

### Stale `pytest.importorskip(... reason='phase-N — module not yet introduced')`

Each succeeds today; the reason string is dead and the silent-skip hides a real import failure. Delete and replace with direct top-of-file imports.

- `inspector/tests/classifier/test_classify_per_category.py:11`
- `inspector/tests/registry/test_registry_behavior.py:11`
- `inspector/tests/registry/test_registry_policy.py:10`
- `inspector/tests/registry/test_registry_extensibility.py:10`
- `inspector/tests/identity/test_validation_identity.py:38, 53, 70, 81`
- `inspector/tests/routes/test_route_data.py:55-58`

### Stale fixtures/expected files

- `inspector/tests/fixtures/segments/expected/registry-snapshot.json` — orphaned (no regenerator, no consumer, already stale: 11 categories vs the live 13). Delete or wire a regenerator + drift gate.
- `inspector/tests/fixtures/segments/112-ikhlas.edit_history.jsonl` — full of dead `_OP_DEAD_FIELDS` (`file_hash_after`, `reciter`, `save_mode`, `applied_at_utc`, `ready_at_utc`, `started_at_utc`, `patch`, `type`) and missing the v2-required `actor` block. Rewrite as canonical v2 + add a `test_on_disk_edit_history_fixture_validates` asserting zero `strip_and_warn` warnings.
- `inspector/tests/fixtures/segments/synthetic-classifier.detailed.json:96` — `wrap_word_ranges` typed as `[[int]]` not `[[str]]`; fails `DetailedDocument.model_validate`. Either fix the fixture to use string verse-word refs, or widen the schema, but make them agree. Extend `test_on_disk_fixture_validates` to cover the synthetic fixtures.
- Synthetic fixtures (`synthetic-structural.detailed.json:46,53`, `synthetic-classifier.detailed.json:73`) carry `matched_text` + `phonemes_asr` on every seg; those are in `_SEG_DEAD_FIELDS` per `qua_shared/schemas/segment.py:44`. Strip them.

### Unused imports

- `inspector/tests/db/test_repo_state.py:5` — unused `timezone`.
- `inspector/tests/routes/test_route_auth.py:18` — unused `datetime, timezone`.
- `inspector/tests/routes/test_route_admin_actions.py:12` — unused `datetime, timezone`.
- `inspector/tests/persistence/test_detailed_schema.py:6`, `test_uid_backfill.py:9` — unused `import pytest`.
- `inspector/tests/command/test_apply_command.py:10` — unused `import pytest`.
- `inspector/tests/routes/test_route_validate.py:4`, `test_route_history.py:7` — unused `import pytest`.
- `inspector/tests/routes/test_route_save.py:118, 120-123, 146, 148-151` — five-line blocks of in-function imports never used.
- `inspector/tests/routes/test_route_requests.py:37-45` — `_isolated_backend` fixture imports five schemas (`ReciterCatalog`, `ReciterRow`, `ReciterState`, `ReciterStateFile`, `Visibility`) never used.
- `inspector/tests/routes/test_route_requests.py:48-51` — fixture aliases `catalog_service` + `state_service` never referenced.
- `inspector/tests/services/test_pending_requests.py:10, 16, 116` — unused `datetime`, `PendingRequest`, `storage_paths`.
- `inspector/tests/services/test_auto_detect.py:33, 35, 37` — fixture imports `catalog_service`, `pending_requests_service`, `storage_paths` it never references.
- `inspector/tests/services/test_state_request_events.py:26, 104-107, 160, 190, 209, 620` — module-level `ReciterStateFile`, fixture-local `request_archive_service` + `storage_paths`, several `from services import storage_paths` re-imports; unused `monkeypatch`/`tmp_path` parameters on lines 532, 578.
- `inspector/tests/routes/test_route_auth.py:71, 85, 100, 118` — `user` unpacked from `signed_in_client` but never used; should be `_`.
- `inspector/tests/services/test_cache_invariants.py:123` — `monkeypatch` parameter declared but never used.
- `inspector/tests/admin/test_identity_recency.py:18` — reaches into private `_serde.now` (low priority).

### Dead arithmetic, redundant lines

- `inspector/tests/services/test_cache_invariants.py:146-152` — pops `_seg_split_group_index` twice with no intervening write; second pop is a no-op.
- `inspector/frontend/src/lib/stores/__tests__/claim-confirm-modal.test.ts:10-13` — `closeClaimConfirm()` then `claimConfirmModal.set({ open: false, slug: null, onClaimed: null })` — the second call fully overwrites; the first is dead. Same anti-pattern in `inspector/frontend/src/lib/components/__tests__/ClaimConfirmModal.test.ts:48-51` and `inspector/frontend/src/lib/components/__tests__/EditAffordancePopover.test.ts:10-16`.
- `inspector/frontend/src/tabs/segments/components/list/__tests__/SegmentsList.test.ts:127, 140` — unused `_endIdx = 60` / `_startIdx = 40` locals; the tests don't reference them.
- `inspector/frontend/src/tabs/segments/components/list/__tests__/SegmentsList.test.ts:12, 17-21` — `FakeSeg.chapter` is set but never read.
- `inspector/tests/persistence/test_segment_schema.py:104, 228`, `test_peaks_history_schema.py:133` — `import logging` inside function bodies despite top-of-file imports being available. Hoist.
- `inspector/services/db/migrate.py` `_NAME_RE` skip path — module reference path now `services.activity.search_normalize.py:1` lists wrong path (docstring drift).

### Misplaced test (file under tests/scripts/ but tests qua_shared)

- `inspector/tests/scripts/test_ts_validation.py:9` — imports `from qua_shared.timestamps_pipeline import build_ts_validation`. Move to `inspector/tests/qua_shared/test_timestamps_pipeline.py` (or `qua_shared/tests/`).

### File misnamed for what it tests

- `inspector/frontend/src/tabs/segments/components/list/__tests__/SegmentsList.test.ts` — every assertion in it is on `virtualization.ts`, none on `SegmentsList.svelte`. Rename to `virtualization.test.ts`.
- `inspector/frontend/src/tabs/timestamps/services/__tests__/ts_client.test.ts` — covers only `assembleVerseFromShard` / `chapterVerseRefs` / `vbrChaptersFromManifest` / `resolveVbrChaptersForReciter`; tested in `lib/recitation-data/ts-source.ts`. The barrel file's docstring at `services/ts_client.ts:1-11` references "implementation moved" — drop the refactor narrative.
- `inspector/tests/routes/test_route_history_peaks_lock.py` — no test exercises lock semantics; rename to `test_route_history_peaks.py`.
- `inspector/tests/db/test_repo_requests_activity.py` — mixes requests + activity; the lone activity test (line 97-113) belongs in a `test_repo_activity.py`. Split.
- `inspector/tests/routes/test_route_admin_actions.py:3-6` docstring claims `state/force-set` coverage but no such route exists; either remove the claim or stop asserting absent behavior.
- `inspector/tests/routes/test_route_access_admin.py:5,7` docstrings claim "403 on cross-origin POST" and "409 on already-active member"; no test for cross-origin (only missing-Origin) and no test for the 409 mapping.

### Skip-on-missing-fixture should be hard fail

- `inspector/tests/persistence/test_segment_schema.py:250-266` — `pytest.skip(f"fixture missing: {fixture_path}")` on shipped fixtures (`112-ikhlas`, `113-falaq`). Replace with `assert fixture_path.is_file()`. Committed fixtures missing = regression, not skip condition.

### Misleading raise vs skip in history test

- `inspector/tests/routes/test_route_history.py:59-82` — raises AssertionError when batches is empty (`raise AssertionError('phase-5: no batches yet to inspect')`); docstring says "absence of batches keeps the test in xfail". Replace with `pytest.skip(...)` or seed a batch via signed_in_client.

### Wrong-but-dead BE fallback

- `inspector/tests/conftest.py:58-78` — fallback `ALL_CATEGORIES` literal lists 11 categories (registry has 13, with `low_confidence_v2` and `basmala_amin`). The fallback is unreachable today but masks silent skew if it ever fires. Delete.

---

## Skip / xfail audit

| file:line | type | reason | verdict |
|---|---|---|---|
| `inspector/tests/classifier/test_classify_per_category.py:11` | `pytest.importorskip` | "phase-2 — unified classifier not yet introduced" | **delete** — `services/validation/classifier.py` exists |
| `inspector/tests/registry/test_registry_policy.py:10` | `pytest.importorskip` | "phase-1 — IssueRegistry module not yet introduced" | **delete** — `registry.py` exists |
| `inspector/tests/registry/test_registry_behavior.py:11` | `pytest.importorskip` | "phase-1 — IssueRegistry module not yet introduced" | **delete** |
| `inspector/tests/registry/test_registry_extensibility.py:10` | `pytest.importorskip` | "phase-1 — IssueRegistry module not yet introduced" | **delete** |
| `inspector/tests/routes/test_route_data.py:55-58` | `pytest.importorskip` | "phase-1 — IssueRegistry module not yet introduced" | **delete** |
| `inspector/tests/identity/test_validation_identity.py:38` | `pytest.importorskip` | "phase-6 — services.validation.detail not yet present" | **delete** — module exists |
| `inspector/tests/identity/test_validation_identity.py:53` | `pytest.importorskip` | "phase-6 — ..." | **delete** |
| `inspector/tests/identity/test_validation_identity.py:70` | `pytest.importorskip` | "phase-6 — ..." | **delete** |
| `inspector/tests/identity/test_validation_identity.py:81` | `pytest.importorskip` | "phase-6 — ..." | **delete** |
| `inspector/tests/identity/test_validation_identity.py:97-114` | naive walk | `test_no_index_fixups_after_phase_6` walks for foreign worktree slug | **reframe** — anchor at `Path(__file__).parents[N]` |
| `inspector/tests/routes/test_route_history.py:74-82` | `AssertionError` masquerading as xfail | "phase-5: no batches yet to inspect" | **reframe** — `pytest.skip(...)` or seed a batch |
| `inspector/tests/persistence/test_segment_schema.py:260` | `pytest.skip` | "fixture missing: …" | **reframe** — hard assert; fixtures are shipped |
| `inspector/frontend/src/tabs/segments/__tests__/registry/policy.test.ts:47-49` | `describe.skipIf(truthy)('... (deferred)')` | "phase-1: domain/registry not yet present" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/registry/parity.test.ts:42-44` | `describe.skipIf(truthy)` deferred | "phase-1" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/registry/behavior.test.ts:65-67` | `describe.skipIf(truthy)` deferred | "phase-1" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/apply-command.test.ts:73-75` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/auto-suppress.test.ts:93-95` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/delete.test.ts:60-62` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/ignore.test.ts:64-66` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/merge.test.ts:63-65` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/reference.test.ts:62-64` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/split.test.ts:242-244` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/command/trim.test.ts:79-81` | `describe.skipIf(truthy)` deferred | "phase-3" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/normalized-state/compat.test.ts:32-34` | `describe.skipIf(truthy)` deferred | "phase-4" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/normalized-state/uid-backfill.test.ts:38-40` | `describe.skipIf(truthy)` deferred | "phase-4" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/identity/stale-filter.test.ts:32-34` | `describe.skipIf(truthy)` deferred | "phase-6" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/identity/resolve-issue.test.ts:91-93` | `describe.skipIf(truthy)` deferred | "phase-6" | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/save/payload-shape.test.ts:29, 31` | `throw new Error('phase-3: build helper not yet present')` | dead defensive throws — `utils/save/payload.ts` exists | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/save/patch-included.test.ts:8, 11` | `throw new Error('phase-5: builder not yet present')` | dead | **delete** |
| `inspector/frontend/src/tabs/segments/__tests__/helpers/optional.ts:9-18` | `loadOptional` swallow-all helper | only callers are the deferred blocks above | **delete** (after callers go static) |
| `inspector/frontend/src/tabs/segments/__tests__/helpers/xfail.ts:13` | `xfail(reason, fn)` helper | zero callers | **delete** |
| `inspector/tests/routes/test_route_history.py:23` etc. (5 sites) | `assert status_code in (200, 404)` | shape check gated behind 200 branch | **reframe** — hard `== 200` |

### Stale FE phase-1 module gates — comprehensive list

All four "phase-N (module foo) not yet present" gates referenced in the deferred blocks are stale; the target modules exist:

| Gated module | Status | Source path |
|---|---|---|
| `domain/registry.ts` | exists | `inspector/frontend/src/tabs/segments/domain/registry.ts` (`IssueRegistry` at line 31) |
| `domain/apply-command.ts` | exists | `inspector/frontend/src/tabs/segments/domain/apply-command.ts` (`applyCommand` at line 662) |
| `domain/identity.ts` | exists | `inspector/frontend/src/tabs/segments/domain/identity.ts` (`deriveUid` at line 133, `backfillSegmentUids` at line 158) |
| `utils/validation/stale.ts` | exists | `inspector/frontend/src/tabs/segments/utils/validation/stale.ts` (`filterStaleIssues`) |
| `utils/validation/resolve-issue.ts` | exists | `inspector/frontend/src/tabs/segments/utils/validation/resolve-issue.ts` |
| `stores/chapter.ts` | exists | `inspector/frontend/src/tabs/segments/stores/chapter.ts` |
| `stores/segments.ts` | exists | `inspector/frontend/src/tabs/segments/stores/segments.ts` |
| `stores/filters.ts` | exists | `inspector/frontend/src/tabs/segments/stores/filters.ts` |
| `utils/save/payload.ts` | exists | `inspector/frontend/src/tabs/segments/utils/save/payload.ts` (`buildPayloadFromCommandResult`) |

---

## Mocking / isolation / fixture consolidation (for the corrections PR)

### Conftest promotions

| Helper | Currently | Target |
|---|---|---|
| `INSPECTOR_SESSION_SECRET` setdefault (28 files) | per-file module-level `os.environ.setdefault` | autouse session fixture at top of `inspector/tests/conftest.py`; delete per-file lines |
| `_row(slug, **overrides)` + `_replace_state` | duplicated in 4 route test files with divergent defaults | promote `row_spec` + `seed_rows` to `tests/conftest.py` |
| `_hf_user(...)` + `_stub_hf_users` | only in `test_route_admin_actions.py:58-78` | `hf_user_factory` + `stub_hf_users` fixtures in `tests/conftest.py` |
| `_actor()` factory | 11 files redefine inconsistently | `make_actor` factory fixture (`tests/conftest.py`); kw-only `(hf_user_id, login, role)` |
| `_patch_whoami` + autouse `_clear_token_cache` | duplicated in `test_route_intake_ingest.py:89-100` + `test_token_auth.py:24-34` | promote to `tests/conftest.py` (or `tests/services/_bearer.py`); make `_clear_token_cache` autouse |
| `_clean_validation` validate stub | duplicated `test_route_claims.py:45-74` and inline `test_state_parity.py:194-200` | promote to `tests/conftest.py` with full 6-key shape; use fixture |
| `_ins_transition` + `_ins_request` | inlined raw-SQL in `test_users_read.py:9-21` + `test_first_seen_backfill.py:34-46, 73` | promote `seed_transition`, `seed_request` next to `seed_state`/`seed_role` |
| `_isolated_backend` (route) ≈ `fs_backend` (service) | duplicated FilesystemBackend + vocab/reciter seed | `intake_fs_backend` composing `state_persistence` + `_intake_vocab_and_reciter` |
| `_seg_payload_from_fixture` | local in `test_save_clears_ignores.py`, duplicated inline 5 other places | promote to `tests/conftest.py` |
| `_segments(detailed)` flattener | duplicated `test_detailed_schema.py:38-43` + `test_uid_backfill.py:19-23` | promote |
| `_HEADERS` (Content-Type + Origin) | duplicated across persistence tests + inline elsewhere | promote to `tests/conftest.py` as module-level constant |
| `_ok` MFA-builder + `_chapter_loopback`/`_results_loopback` + `PROVENANCE` | duplicated across 3 qua_shared test files | add `qua_shared/tests/conftest.py` |
| `flushMicrotasks` + `setVisibility` + `dispatchVisibilityChange` | only in `visible-poll.test.ts` | promote to `lib/test-helpers/` |
| `load_script(name, path)` importlib boilerplate | duplicated in `test_make_fixtures.py:25`, `test_update_readme_badges.py:15`, `test_migration.py:28` | promote to `inspector/tests/conftest.py` (or `tests/scripts/conftest.py`) |
| `makeApplyCommandState(segments, opts)` | inlined `baseState()` factory in 7 command test files | helper in `__tests__/helpers/make-segment.ts` |
| `makeSegmentState(segs, chapter)` | inlined per test file | helper in `__tests__/helpers/make-segment.ts` |
| `FakeIntersectionObserver` stub | inline in `AccordionGuideModal.test.ts`, missing from `MissingWordsCard.test.ts` | hoist into `vitest.setup.ts` or `__tests__/helpers/dom-stubs.ts` |
| `_clear(monkeypatch)` env reset | repeated 7 times in `test_bucket_guard.py` | autouse fixture in that file |
| `categories` snapshot matrix | duplicated in `parity.test.ts:14-28` + `policy.test.ts:14-28` | extract to `helpers/registry-snapshot.ts` or codegen from Python |
| `record_audit_calls(monkeypatch)` | 3 inconsistent inline patterns | shared helper that normalizes kwargs |

### Mocking-boundary policy

| Boundary | Convention | Don't |
|---|---|---|
| **BE bucket / data dir** | `tmp_reciter_dir` or `state_persistence` (installs `FilesystemBackend`, sets `INSPECTOR_BACKEND=filesystem`) | patch `Path.read_text`, mock `hf_bucket` internals |
| **BE env vars** | `monkeypatch.setenv` | mutate `os.environ` directly at module load |
| **BE HF OAuth / identity** | `signed_in_client(role=...)` | mock `auth_service.encode_session` |
| **BE external HTTP** (QF, HF API) | monkeypatch the specific service function | mock `requests.get` |
| **BE caches** | rely on autouse teardown; add new caches to `_SEG_CACHE_NAMES` | mock cache primitives |
| **BE audit** | record-and-call-through (capture `kwargs` to a list) + assert against `repo_transitions.for_slug(slug)` | replace with `lambda **kw: None` (loses the durability check) |
| **FE modules** | real imports + props-driven state | `vi.mock(...)` for non-ambient modules |
| **FE fetch** | `vi.spyOn(window, 'fetch')` | global mock that returns 200 `{}` for every URL |
| **FE stores** | real store + `set()` in test | mock the store |

### Specific isolation fixes

- `inspector/tests/db/test_sync.py:127-139` upload-failure test: the `"no token/url leakage"` comment is unsupported by the assertion. Either drop the comment or raise an exception with a 1000-char token-bearing string and assert truncation + redaction.
- `inspector/services/db/sync.py:71-73` `_safe_err` truncation is currently the only safety net. Add a direct unit test.
- `inspector/tests/conftest.py:362-376` `_SEG_CACHE_NAMES` omits `_seg_history_peaks_response`. Add it.
- `inspector/tests/services/test_op_peaks.py:180-190` `test_seg_invalidation_helpers_pop_response_cache` mutates a module-level cache without fixture cleanup. Use `tmp_reciter_dir` (which already clears via `_invalidate_seg_caches`) or randomize the slug.
- `inspector/tests/routes/test_route_public.py:10`, `test_route_public_activity_delete.py:14` — drop the module-level setdefault; the public-route tests are anonymous and don't need the secret.
- `inspector/tests/services/test_activity_state.py:22-24` `fresh_state` monkeypatches three env vars `activity_state` never reads. Strip.
- `inspector/tests/services/test_request_archive.py:26-28` `fresh_archive` yields `(svc, backend)` but every test discards `backend`. Yield only `svc`.
- `inspector/tests/admin/test_users_read.py:77-90` `test_detail_outcome_and_stats` hand-INSERTs delivery + claim instead of using repo helpers. Use `_seed_delivery_chain` + repo_claims.
- `inspector/frontend/src/tabs/segments/__tests__/normalized-state/selectors.test.ts:55-118` mutates `chapterStore.segAllData` + `selectedChapter` without `beforeEach`/`afterEach`. Adopt the `resolve-issue.test.ts` pattern (`beforeAll`/`afterAll` with `setupStore` returning a teardown closure).
- `inspector/frontend/src/lib/utils/__tests__/goto-segments.test.ts:9-17` — `afterEach` resets the `activeTab` store but not the imperative scalar `_activeTab`. Use `setActiveTab(TAB_NAMES.DASHBOARD)` instead of `activeTab.set(...)`.
- `inspector/tests/db/conftest.py:11` `fresh_db` redundantly reinitializes the DB the autouse `_substrate_db` already provisioned; opt out for `test_spine.py`'s local copy too.
- `inspector/tests/services/test_manifest_invalidation.py:38-50, 96-109` — autouse `_substrate_db` clears db-seq caches but not `ts_manifest._built` / `_built_seq` / `_served_slugs` etc. Add `ts_manifest.invalidate()` to a local autouse or to the substrate fixture.

### Vitest setup

- `inspector/frontend/vitest.setup.ts:7-27` — global fetch mock returns 200 `{}` for every URL except a special-cased surah-info path. Either keep as-is and document it, or migrate to MSW with default-404 handlers. The redundant conditional for surah-info can be simplified.

---

## Schema / codegen parity gaps

CLAUDE.md's writer/reader-shape convention says per-reciter artefacts MUST round-trip through `qua_shared/schemas`. Current state:

| Artefact | Round-trip test | Status |
|---|---|---|
| `detailed.json` (DetailedSegment) | `inspector/tests/persistence/test_segment_schema.py` | ✅ exists; needs `is_wasl` added to `KNOWN_SEGMENT_FIELDS`; needs auto-derivation from `DetailedSegment.model_fields`; needs synthetic fixtures fixed |
| `edit_history_peaks.jsonl` (PeaksRecord) | `inspector/tests/persistence/test_peaks_history_schema.py` | ✅ exists; needs negative-bound parametrize (start/end < 0) |
| `edit_history.jsonl` (EditHistoryBatch + EditOperation) | **none** | ❌ missing — see below |
| `catalog/audio_manifest/<slug>.json` (AudioManifestSidecar) | **none** | ❌ missing — see below |
| Slim FE subset (`fe_types.py`) | `schema-codegen-check` CI job + `git diff --exit-code` on `schemas.ts` | ✅ exists; misses additions — see below |

### Missing: `EditHistoryBatch` / `EditOperation` round-trip test

**Contract at risk.** CLAUDE.md line 137 mandates round-tripping. Inspector save flow (`inspector/services/segments/save.py:432-441`) writes batches with `schema_version`, `batch_id`, `chapter`, `saved_at_utc`, `save_mode`, `operations`, `actor`. Operations carry `classified_issues` on snapshots (lines 209-212). Reader (`inspector/services/activity/history_query.py:93`) uses `orjson.loads()` without schema validation. A writer dropping a required field would not be caught until a downstream consumer fails.

**Proposed action.** Add `inspector/tests/persistence/test_edit_history_schema.py`:
- Load `inspector/tests/fixtures/segments/112-ikhlas.edit_history.jsonl` (after the fixture is rewritten to canonical v2 — see "Dead / legacy tests").
- Parse every line via `parse_edit_history_line`.
- Assert `caplog.records` contains zero WARNING entries (only INFO legacy strips are acceptable).
- Add canonical-shape and dead-field-stripping tests mirroring the `PeaksRecord` suite.
- Add tests for: batch with `chapter` vs `chapters` mutual exclusion; `reverts_batch_id`/`reverts_op_ids` carrying through; v2 batch with `file_hash_after` legacy field; batch with `batch_pill`/`save_mode`/`ts` dead fields; op-level dead-field stripping (`applied_at_utc`, `command`, `type`, `value`); `targets_before`/`targets_after` snapshot with extra seg fields; `validation_summary_before/after` legacy emptied.
- Assert dead-field set parity vs the real writers at `.local/extraction/segments/post_passes.py` and Inspector save.

### Missing: `AudioManifestSidecar` round-trip test

**Contract at risk.** `qua_shared/schemas/catalog.py:327-349` defines `AudioManifestSidecar` with nested `extra='forbid'` `SidecarMeta` and `ChapterEntry`, plus `populate_by_name=True` with the `_meta` alias. Inspector ingest (`inspector/services/admin/intake.py:432-460`) writes through the schema; readers (`audio_meta.py`, `audio_source.py`) read raw JSON without schema validation. Schema drift goes silent on read.

**Proposed action.** Add `inspector/tests/fixtures/audio_manifest/<slug>.json` (a real-world sidecar shape) and `inspector/tests/persistence/test_audio_manifest_schema.py`:
- Canonical by_surah with int chapter keys stringified.
- by_ayah with `'<sura>:<ayah>'` keys.
- `_meta` alias round-trip (in JSON ↔ `.meta` in Python with `by_alias=True`).
- `ChapterBitrateMode` (CBR/VBR) parsing.
- `bitrate_kbps=None` tolerance.
- Slug regex enforcement.
- `extra='forbid'` rejection of unknown nested-model fields.
- Forward-compat case (extra field in `_meta`).

### Missing: subset-completeness guard for `fe_types.py`

**Contract at risk.** `scripts/codegen/regen_fe_types.py` walks `SCHEMAS_MODULE = 'qua_shared.schemas.fe_types'`. Only models re-exported there land in `inspector/frontend/src/lib/types/generated/schemas.ts`. CI's `schema-codegen-check` catches "forgot to regen" but not "added a new model to `qua_shared/schemas/X.py` + a new FE consumer, but forgot fe_types.py". Live evidence: `inspector/frontend/src/lib/api/requests.ts:26` hand-rolls `export interface PendingRequest` even though `qua_shared/schemas/pending_requests.py::PendingRequest` exists in canonical schemas — but is not in `fe_types.py`.

**Proposed action.** Add a parity test: every `BaseModel` subclass under `qua_shared.schemas` that is referenced by `inspector/frontend/src/lib/api/**/*.ts` or `inspector/frontend/src/tabs/**/types.ts` appears in `qua_shared.schemas.fe_types.__all__`. Or invert the convention so `fe_types.py` re-exports the full set and the codegen runs against `qua_shared.schemas` directly.

### Missing: BE↔FE search-normalize parity test

**Contract at risk.** `inspector/services/activity/search_normalize.py:1-12` and `inspector/frontend/src/lib/utils/fuzzy-match.ts:8-10` docstrings both claim load-bearing symmetry. No shared fixture; the FE regex drifted and caught the bug at the top of this report.

**Proposed action.** Add `inspector/tests/fixtures/search_normalize_golden.json` (list of `{input, expected_normalized}` rows covering every regex range — tashkeel U+064B-U+065F, Quranic annotations U+0610-U+061A, U+06D6-U+06DC, U+06DF-U+06E4, U+06E7-U+06E8, U+06EA-U+06ED, alif variants, taa-marbuta, alif-maqsura, dagger alef U+0670). Assert against it from both `test_search_normalize.py` and `fuzzy-match.test.ts`. Future drift fails simultaneously.

### Missing: BE BLOCKING_COUNT_KEYS parity test

**Contract at risk.** `qua_shared/schemas/mark_ready.py:43-50` and FE `inspector/frontend/src/tabs/segments/copy/mark-ready/index.ts:36-45` must mirror. FE `inspector/frontend/src/tabs/segments/__tests__/parity/mark-ready-copy.test.ts:73-86` enforces FE-side. **Proposed action.** Add a BE pytest (or codegen) asserting `BLOCKING_COUNT_KEYS == ('low_confidence','low_confidence_v2','boundary_adj','cross_verse','basmala_amin','repetitions')`, and ideally codegen the FE list from the BE.

### Missing: BE↔FE Codes parity test

**Contract at risk.** `inspector/frontend/src/lib/errors/friendly.ts:10` and `inspector/services/errors.py:25-27` both claim lockstep, but nothing enforces it. A new BE code added without updating `CODE_COPY` falls through to the generic status message.

**Proposed action.** Add `inspector/tests/test_errors_parity.py` that parses `services/errors.py::Codes` string constants and verifies every value appears as a key in `CODE_COPY` (parse the FE file as text). Sister job to `schema-codegen-check`.

### Missing: TS↔Python registry parity description coverage

See section 4 — `parity.test.ts:14-28` omits `description`, `displayTitle`, `accordionOrder`. Real drift exists in `repetitions` and `cross_verse` descriptions. Either extend `PY_SNAPSHOT` to include those fields, or generate the parity baseline from `registry_as_dict()` at codegen time.

### Schemas smoke is not run by CI

`qua_shared/schemas/smoke.py` exists with `__main__` entrypoint but is invoked by zero CI workflows. The docstring at `qua_shared/schemas/_extras.py:19` advertises it as "Tests live alongside the schemas (qua_shared/schemas/smoke.py)". **Proposed action.** Migrate its checks into proper pytest under `qua_shared/tests/` (preferred — CI already runs `pytest qua_shared/tests`). Drop or update the docstring. Also fix `smoke.py:236, 240`: `EditHistoryBatch(..., ts=...)` and `EditOperation(..., new_end=...)` — both fields are dead per the current schema; the round-trip passes because both sides equally strip them.

---

## CI test-execution observations

### Duplicate runs of the same checks workflow on push to `main`

`docker-publish.yml:4-10, 49-51` and `inspector-deploy.yml:3-16, 41-43` both `uses: ./.github/workflows/inspector-checks.yml`. Path filters overlap (`inspector/**`, `qua_shared/**`, `qua_jobs/**`). On a `main` push both fire in parallel — duplicate CI minutes, double autofix-commit risk. **Proposal.** Either gate `inspector-deploy.yml`'s `checks` job behind a `needs:` on `docker-publish.yml`'s status, have deploy reuse the docker-publish artifact via SHA, or drop `main` from `docker-publish.yml`'s branch list and let deploy own main-push checks.

### `git add -A` in autofix step is repo-wide

`.github/workflows/inspector-checks.yml:35-41` — `git add -A` from `inspector/frontend` is repo-wide regardless of cwd. Future incidental tree mutations (`.eslintcache`, tool-generated files) would be committed under the "autofix import sort" message. **Proposal.** Use `git add -- src/` (explicit pathspec) and add `.eslintcache` + common tool caches to `.gitignore`. Optionally add a guard `git diff --name-only | grep -v '^inspector/frontend/src/' && exit 1` between `eslint --fix` and `git commit`.

### qua_shared tests run without inspector's `addopts`

`.github/workflows/inspector-checks.yml:74-82` runs `python -m pytest qua_shared/tests` from `${{ github.workspace }}`. No pyproject.toml/pytest.ini exists at the qua_shared layer; inspector/pyproject.toml `addopts` (-ra, --strict-markers) and coverage config are not applied. **Proposal.** Add `qua_shared/pyproject.toml` with matching `[tool.pytest.ini_options]`, or pass `-ra --strict-markers` explicitly to the CI command. Document the chosen approach.

### `schema-codegen-check` installs only requirements-dev.txt

`.github/workflows/inspector-checks.yml:106-112` — runs `pip install -r inspector/requirements-dev.txt`, which pulls only pytest, pytest-cov, pydantic-to-typescript. Pydantic resolves via pydantic-to-typescript's transitive dep instead of inspector/requirements.txt's pinned `pydantic>=2.10`. **Proposal.** Also `pip install -r inspector/requirements.txt` in this job. One-line cost; eliminates the version-skew risk between codegen and runtime.

### No determinism test for codegen pipeline

`schema-codegen-check` relies on `regen_fe_types.py` producing byte-identical output twice. If pydantic-to-typescript or json-schema-to-typescript ever introduces nondeterminism (set order, timestamp comments, JSON key order), every PR will fail. **Proposal.** Add a small test (in CI before drift check, or as inspector pytest) that runs the codegen twice to a temp dir and diffs. Fails fast with a clear error.

### qua_jobs/ has no coverage

CI Python coverage is `--cov=.` rooted at `inspector/` (one run) and `--cov=qua_shared` (other run). `qua_jobs/` (cut_release, publish_hf, generate_timestamps, shard) is neither tested nor measured. **Proposal.** Decide: if intentionally untested, document the gap. If wiring desired, extend the qua_shared run with `--cov=qua_jobs` or add a third pytest step.

### Coverage gap on duplicate-target uploads

`scripts/devenv/make_fixtures_dataset.py:158-170` (and friends) deduplicate `seen_targets`. Test in `test_make_fixtures.py:51-56` converts manifest's adds list to a set, silently deduplicating; a regression that duplicated targets would not fail. **Proposal.** After collecting targets, assert `len(targets) == len([t for _s, t in stub_batch[0]['add']])`.

### Stale coverage glob

`inspector/pyproject.toml:25` lists `*/__init__.py` in `omit`. Several non-trivial `__init__.py` files carry real boot logic: `routes/__init__.py:17-78` (`register_blueprints`), `services/__init__.py:13-99` (sys.modules aliasing), `services/db/__init__.py:25-39` (`init_db`/`healthcheck`), `services/validation/__init__.py:38-241` (`validate_reciter_segments`). The blanket omit hides whether the boot path is exercised. **Proposal.** Drop `*/__init__.py` from `omit`; `skip_empty = true` (already set) keeps trivial shims out of the report.

### `.bucket/*` omit pattern is no-op in CI

`inspector/pyproject.toml:24` — `.bucket/` is created at repo root, not in inspector/. With `source=['.']` from inspector/, the pattern matches nothing. Harmless but misleading. **Proposal.** Drop the line or document it as local-only protection.

### Backend `branch=false` vs FE branch coverage

`inspector/pyproject.toml:20` sets `branch = false`. FE v8 provider reports branch by default. Asymmetric headline numbers between BE and FE. Acceptable for first cut; **document** the asymmetry in the testing.md follow-up doc so future readers don't conclude "BE is twice as well-tested as FE".

### qua_shared coverage not unified with inspector

Two separate coverage runs produce two `.coverage.xml` files. Per-PR coverage delta has to be read across two files. **Proposal.** Either document the split explicitly, or add a CI step that combines them via `coverage combine` before writing the final XML.

### inspector/tests/scripts coverage gap

`inspector/tests/scripts/test_*.py` exercises code in `scripts/devenv/`, `scripts/codegen/`, `.github/scripts/` — not measured because `source=['.']` is rooted at inspector/. **Proposal.** Include `../scripts` and `../.github/scripts` in `source` if unifying coverage, or document.

### Vitest `coverage.all: true` instruments legacy files

`inspector/frontend/vitest.config.ts:17-32` — coverage instruments every file under `src/**/*.{ts,svelte}` including TimestampsWaveform.svelte and canvas/audio-imperative components that CLAUDE.md flags as indefinitely-legacy. Dilutes signal. **Proposal.** Add `exclude` entries for the indefinitely-legacy files (TimestampsWaveform.svelte, WaveformCanvas.svelte, SegmentWaveformCanvas.svelte) so they don't dominate the 0% list. Update CLAUDE.md to point at `docs/reference/frontend.md` (or create `docs/planning/svelte-migration.md` — the doc CLAUDE.md references but doesn't exist).

### Vitest exclude misses `src/**/types.ts` files

`vitest.config.ts:22-30` covers `*.test.ts`/`*.spec.ts`, `__tests__/**`, `lib/types/generated/**`, `*.d.ts`, setup, config. Missing: `src/**/types.ts` (type-only files, no runtime). **Proposal.** Add to exclude. `src/main.ts` (SPA bootstrap, 0% reachable from unit tests) should NOT be excluded — leave it visible as a known low-coverage hotspot.

### "Done in this PR" — coverage-infra wiring

This PR wires the following without enforcing thresholds:

- `inspector/pyproject.toml` — coverage.run.source=['.'], omit list (with the corrections above where in-scope).
- `inspector/frontend/vitest.config.ts` — v8 provider, `coverage.all: true`, exclude for `lib/types/generated/**`, `*.test.ts`/`*.spec.ts`, `__tests__/**`, `*.d.ts`, vitest.setup, config files.
- `.github/workflows/inspector-checks.yml` — `--cov` flags on the two pytest invocations; `npm run test:coverage` on FE; coverage summary emission to GitHub Step Summary; no threshold.

---

## Coverage infrastructure (this PR)

The coverage-infra changes wired in this PR are deliberately minimal: measurement-only, no gating, no thresholds.

**Backend.**
- `inspector/pyproject.toml` `[tool.coverage.run]`: `source = ['.']`, `omit` for `tests/*`, `frontend/*`, `.bucket/*`. (See section 7 for proposed cleanups deferred to the corrections PR — dropping `*/__init__.py`, dropping `.bucket/*` or making it explicit.)
- `[tool.coverage.report]`: `skip_empty = true`, `show_missing = true`.
- pytest invocations in CI add `--cov=services --cov=routes --cov=domain --cov=adapters --cov-report=term-missing --cov-report=xml:.coverage.xml` for the inspector run; `--cov=qua_shared --cov-report=xml:.coverage-qua-shared.xml` for the qua_shared run.
- `branch = false` for this baseline (kept off intentionally — 2× speed cost; can be enabled later once readers have the line baseline).

**Frontend.**
- `inspector/frontend/vitest.config.ts` `coverage`: `provider: 'v8'`, `all: true`, `reporter: ['text', 'json', 'html']`, `thresholds: undefined` (explicit), `exclude: ['src/lib/types/generated/**', '**/*.test.ts', '**/*.spec.ts', '**/__tests__/**', '**/*.d.ts', 'vitest.setup.ts', '**/*.config.{ts,js,cjs,mjs}']`.
- CI invokes `npm run test:coverage` and uploads `coverage/coverage-final.json`.

**CI summary emission.** Both coverage runs emit a one-line `>>> COVERAGE: lines=<N>/<M> branches=<...>` to `$GITHUB_STEP_SUMMARY` so reviewers see the headline number in the PR check.

**What this PR explicitly does NOT do.** No `fail_under`, no threshold checks, no failing-the-build on coverage drop, no CODECOV integration, no coverage diff on PR.

---

## Coverage gaps (for the follow-up gap-filling PR)

Grouped by subsystem. Each gap states what's not protected, why it matters, and the proposed test shape.

### State / repo

- **`repo_state.update_state` unhappy paths (KeyError on unknown column, empty-fields short-circuit).** `inspector/services/db/repo_state.py:151-157`. Test: `update_state('d1')` no-op returns cleanly; `update_state('d1', bogus=1)` raises KeyError; updates of `revision_in_progress`/`last_job_finished_at`/`visibility_reason` round-trip via `get_row`.
- **`repo_transitions.feed` offset/limit pagination + `since()` cutoff.** `repo_transitions.py:147-162`. Test: `feed(limit=2, offset=1)` returns middle slice newest-first; `since(cutoff_iso)` yields only records `>= cutoff` newest-first; `since` with limit truncates.
- **`repo_claims.set_marked_ready` submission-column round-trip + unmark-clears-all-five.** `inspector/services/db/repo_claims.py:97-132`. Test: write all five columns; query; call `set_marked_ready(ready=False)`; assert all five are NULL on the open claim.

### Catalog / requests

- **`find_source` / `add_source` / `find_channel` / `add_channel` direct repo tests.** `inspector/services/db/repo_catalog.py:287-342`. Test: Duplicate raise on existing slug; round-trip JSON serde of `host_patterns`/`audio_categories`; `gh_release_eligible` boolean coercion; `find_source/channel` None for unknown.
- **`latest_gh_release_summary` LEFT JOIN aggregates.** `inspector/services/db/repo_releases.py:196-214`. Test: empty release yields `member_count=0, total_bytes=0`; multi-member sums correctly; superseded excluded.
- **`stamp_stale_on_ts_regen` gh_release_recitations branch.** `inspector/services/db/repo_releases.py:116-143`. Test: seed gh_release + recitation, assert n==2 and gh_release_recitations.stale_since is stamped while older superseded rows are not.
- **`resolve_by_id` back-fill (re-resolve accepted+null-slug)** and rejection branches. `inspector/services/db/repo_requests.py:177-212`.
- **Per-admin view-mark API.** `mark_viewed`/`is_viewed`/`viewed_ids_for_user`/`count_unviewed_open_for_user` at `repo_requests.py:327-361`. Test idempotent INSERT OR IGNORE + the count filter.
- **`admin_list_rows` ORDER BY pending oldest-first / terminal newest-first.** `repo_requests.py:302-324`.
- **`set_payload(request_id, payload)`** public API. `repo_requests.py:215-223`.
- **`repo_review_views.mark_viewed` / `viewed_at_for_user` / `count_unviewed_for_user`** — no direct tests; only indirect via service. `inspector/services/db/repo_review_views.py:18-82`. Test ON CONFLICT upsert, dict shape, `released_at IS NULL` filter, under_review-only guard, ensure_user FK-priming, MAX(IFNULL()) behavior.

### Auth / route-auth

- **`_safe_return_path` open-redirect defense.** `inspector/routes/auth/auth.py:40-57`. Parametrize over `('/foo', '/foo')`, `('//evil.com/x', '/')`, `('https://evil.com/x', '/')`, `('foo', '/foo')`, `(None, '/')`, `('', '/')`.
- **`_TTLCache` expiry and 256-entry backstop.** `inspector/services/auth/auth.py:78-119`. Monkeypatch `time.time` to advance past TTL; inject >256 entries to exercise backstop.
- **`/api/auth/callback` non-token-exchange branches.** Error early return, missing sub, `ensure_user`-raise swallow, `secure/samesite` cookie attribute flip under `INSPECTOR_BEHIND_PROXY`, `pop_return_path` integration.
- **QF OAuth routes** (qf_login, qf_callback, qf_logout) — fully untested. `inspector/routes/qf_auth.py:56-152`. Stub `services.quran_foundation.oauth.exchange_code`; verify state-mismatch returns error page; success sets `qf_session` cookie.
- **Signed-cookie `SignatureExpired` + `MissingSecret` branches** in `decode_session` and `current_user()`-None-on-missing-payload. `inspector/services/auth/auth.py:246-292`.
- **Token cache TTL expiry + 256-entry backstop + role-mutability.** `inspector/services/auth/token_auth.py:44-103`. Demote between two calls; assert second raises NotOwner without a second whoami.
- **`hf_users.lookup` 4xx-non-404 branch.** `inspector/services/auth/hf_users.py:48-51`. Assert HfUserLookupError 'unexpected status' for 403/429.
- **`INSPECTOR_DEV_<ROLE>_HF_ID`/`_LOGIN` overrides in `_dev_current_user`.** `inspector/services/auth/auth.py:297-325`.

### Admin / users / visitors

- **`POST /api/admin/cut-release`.** `inspector/routes/admin/releases.py:251-299`. Anonymous 401, contributor 403, owner happy path with stubbed launch, same-slug in-flight 409, no eligible candidates 409, launch-raise 502.
- **`POST /api/admin/publish-hf/<slug>` — six untested branches.** Anonymous 401, contributor 403, unknown-slug 404, cross-kind single-flight, cut_release in-flight 409, launch 502.
- **`release-preview` refresh / unchanged / needs_manual_version paths.** Currently only "added" + `_bump_minor`. `inspector/routes/admin/releases.py:100-228`.
- **`releases/status` `summary`, `in_flight`, `latest_gh_release` payload fields.** `inspector/routes/admin/releases.py:342-417`. `days_since_cut` ISO-Z parse fragility too.
- **`/api/admin/permissions` POST toggle anon/missing-Origin gate order.** `inspector/routes/admin/permissions.py:37-39`.
- **`/api/admin/access/update` anonymous-401.** `inspector/routes/admin/access.py:130-140`.
- **`/api/admin/access/grant` 409 already-active.** `inspector/routes/admin/access.py:84-85`.
- **`return_intake` (`POST /api/admin/requests/<rid>/return`) — no route test.** `inspector/routes/claims/requests.py:383-387`. Mirror discard_intake.
- **`/api/admin/requests/<rid>/probe` 404 branch.** `inspector/routes/claims/requests.py:371-380`.
- **`/api/reciter/<slug>/request` body-type validators.** `inspector/routes/claims/requests.py:68-80`. Non-dict proposed_edits / non-string comments / non-bool auto_claim.
- **`POST /api/requests/intake` Pydantic ValidationError 400.** `inspector/routes/claims/requests.py:130-133`.
- **8 admin POST routes lack same-origin (CSRF) coverage.** `reject_soft`, `reject_hard`, `view`, `accept`, `probe`, `return`, `discard`, `undiscard`. Parametrize over (path, body) sending `Origin: http://evil.example`.
- **Ingest 422 vocab-missing route mapping + idempotent re-ingest no-op.** `inspector/routes/claims/requests.py:355-368` + `inspector/services/admin/intake.py:246-255`.
- **Auto_claim flow at HTTP-layer.** `routes/claims/requests.py:78-105`. Submit `auto_claim=true`, fire alignment_completed, assert UNDER_REVIEW with requester as assignee. Mirror for skip path.
- **`cancel_job` orchestrator + route.** `inspector/services/admin/timestamps_jobs.py:590-631`. HF cancel raise; running record → rewrite; terminal record → no rewrite; unknown slug; route 200/404/502.
- **`launch()` env composition + webhook URL/secret threading.** `inspector/services/admin/timestamps_jobs.py:206-308`.
- **`running_job_for` + `_resolve_launched_job_id` label-filter / status logic.** `inspector/services/admin/timestamps_jobs.py:153-203`.
- **`read_job_record` / `list_job_records` per-reciter→legacy fallback + TsJobRecord forward-compat + stub synthesis.** `inspector/services/admin/timestamps_jobs.py:328-371`.
- **`job_status` non-terminal + `fetch_job_logs` failure + log truncation.** `inspector/services/admin/timestamps_jobs.py:374-436`.
- **`_has_any_shard` against real backend.** `inspector/services/admin/timestamps_jobs.py:656-668`.
- **`/api/admin/cut-release` parse-body validators** (bad beam, bad probe_beams type, out-of-range workers, Pydantic ValidationError). `inspector/routes/admin/reviews.py:144-175`.
- **`/api/admin/generate-timestamps/<slug>` single-flight 409** when `running_job_for` returns an id. `inspector/routes/admin/reviews.py:123-126`.
- **`/api/admin/generate-timestamps/<slug>` reciter.publish capability rejection.** `inspector/routes/admin/reviews.py:120-122`.
- **set_role login refresh path.** `inspector/services/admin/users.py:41-98` + `routes/admin/users.py:78-85` (note login is silently dropped on update branch — surface as bug).
- **`AdminUsersResponse` / `AdminUserDetail` Pydantic shape parity.** `inspector/services/admin/users.py:141, 188`.
- **`get_user_detail` zero-state path** (known user, no claims/requests/transitions).
- **`_DETAIL_HISTORY_LIMIT=20` clamp.** `inspector/services/db/repo_admin_users.py:22, 154-178`.
- **`_claim_outcome` non-published branches** (force_released, reassigned, released-without-publish, generic close_reason fallback). `inspector/services/admin/users.py:201-216`.
- **`summary.active_this_week` 7-day cutoff.** `inspector/services/admin/visitors.py:122-132`.
- **`get_visitor_stats() recent[]`.** `inspector/services/admin/visitors.py:168-185`.
- **`start_flush_daemon` idempotency + `_flush_loop` exception swallow.**
- **First-seen backfill `role_assignments.granted_at` source untested.** `inspector/services/db/migrations/0003_backfill_first_seen.sql:27`.
- **`/api/admin/cut-release` env composition with webhook secret.**

### Save / undo / segments / validation

- **`_validate_command_envelopes` rejection paths (3 of 5).** `inspector/services/segments/save.py:60-107`. Non-dict command, non-string command.type are untested. Snake/camel allow-list parity also lacks systematic verification.
- **`/api/seg/undo-ops` happy path + actor + marked_ready / owner-bypass branches.** `inspector/routes/segments/edit.py:51-94`. Currently only "unknown ids" test exists.
- **`_reverse_via_patch` cross-chapter ValueError path.** `inspector/services/segments/undo.py:220-239`. Inject a patch with `affectedChapterIds` outside the batch chapter_set; assert 409 "outside the batch scope".
- **`_apply_full_replace` by_ayah branch (multi-entry per chapter).** `inspector/services/segments/save.py:339-379`. All save tests install single-entry by_surah fixtures.
- **`/data?verse=` filter, `/chapters/<r>`, `/reciters`, `/auto-split/<r>`.** `inspector/routes/segments/data.py:61-133`.
- **Cache-Control headers on `/config`, `/reciters`, `/data`.** `inspector/routes/segments/data.py:55-115`.
- **`/validate` cache hit / 404 / invalidation after `/save`.** `inspector/routes/segments/validation.py:14-24`.
- **`/edit-history` summary shape + `_enrich_snapshot_audio_urls`.** `inspector/routes/segments/validation.py:44-47` + `inspector/services/activity/history_query.py:188-240`.
- **`guides_bp` POST /api/guides/viewed missing-Origin 403.** `inspector/routes/auth/guides.py:32-33`.
- **`guides_bp` 500 path on repo failure + 400 sub-branches** (missing body, non-string category, missing key). `inspector/routes/auth/guides.py:40-51`.
- **`segValidation` filterPersistentIgnores FE.** `inspector/frontend/src/tabs/segments/domain/registry.ts:210-222` (untested despite Python twin having coverage).
- **`segValidation` derived ERROR_CAT_LABELS, PER_*_CATEGORIES, AUTO_SUPPRESS_CATEGORIES.** `inspector/frontend/src/tabs/segments/domain/registry.ts:225-227, 193-198, 257-265`.
- **`_choose_occasion` widest-coverage fallback (no occasion completes).** `qua_shared/timestamps_dedup.py:280-284`.
- **`build_raw_v2` `_meta.mfa_failures` capture.** `qua_shared/timestamps_dedup.py:60-69` + `qua_shared/timestamps_pipeline.py:818-823`.
- **`split_to_shards` + `derive_url_template`** (timestamps_shards.py). Compound-key routing, mfa_failures slicing, audio_urls fallback, deterministic verse-key sort. `qua_shared/timestamps_shards.py:94-378`.
- **`segments_shards.py`** entirely untested (parallel module to timestamps_shards). `qua_shared/segments_shards.py:1-178`.
- **Persistence-cache invariants** for db_seq-keyed caches (catalog_json_bytes, admin_users, admin_requests, capability_matrix). `inspector/services/storage/cache.py:715-827`.
- **`invalidate_audio_manifest_cache` paired-clear contract.** `inspector/services/storage/cache.py:537-544`.
- **`_PEAKS_RESPONSE_CACHE` LRU + per-reciter pop.** `inspector/services/storage/cache.py:395-431`.
- **`_jobs_in_flight` TTL cache.** `inspector/services/storage/cache.py:847-877`.
- **`invalidate_seg_caches` + `pop_seg_caches_affected_by_segment_edit` selectivity.** `inspector/services/storage/cache.py:278-337`.
- **`_KeyedCache` default `_KEYED_CACHE_LRU_MAX = 20`.** Tests construct with `max_size=3`.
- **`_SingletonCache` get/set/clear contract.** `inspector/services/storage/cache.py:22-35`.

### Audio / peaks / VBR

- **`/api/seg/segment-clip` route.** `inspector/routes/audio/clip.py:44-148`. 403 unknown URL; 400 bad start_ms/end_ms; 400 non-http scheme; ffmpeg-missing 500; happy 200 + ACAO + immutable Cache-Control; fail-loud branch (rc!=0, 0 bytes).
- **Audio proxy path branch + _stream_cdn branch + 400 + 502 paths.** `inspector/routes/audio/proxy.py:71-188`.
- **`/api/seg/segment-peaks` per-segment ffmpeg-fallback route.** `inspector/routes/segments/peaks.py:146-181`.
- **History-peaks 400 "records must be a list" branch.** `inspector/routes/segments/peaks.py:230-232`.
- **History-peaks happy-path POST persists record.** `inspector/tests/routes/test_route_history_peaks_lock.py:22-79` covers only negatives.
- **`_HISTORY_POST_MAX_B64` size cap per-record.** `inspector/routes/segments/peaks.py:186, 243-246`.
- **GET /history-peaks empty-state shape, cache reuse, canonical record shape.** `inspector/routes/segments/peaks.py:189-209`.
- **`shadow-audio.ts` prewarm + handoff (4 distinct invariants).** `inspector/frontend/src/lib/playback/shadow-audio.ts:1-231`.
- **`shuffle-prewarm.ts` gapless shuffle handoff.** `inspector/frontend/src/lib/playback/shuffle-prewarm.ts:1-89`.
- **`audio.ts`, `audio-warmup.ts`, `waveform-cache.ts` have no tests** — `safePlay`, `audioSrcMatches`, `normalizeAudioUrl`, `get/set/invalidate` cache.
- **`fetchSegmentPeaks` early-returns + `bps` forwarding + missing-key.** `inspector/frontend/src/lib/utils/peaks-fetch.ts:34-56`.
- **`pickChapterPeaks`** (single-entry returns directly; multi-entry URL-normalised match across audio-proxy ↔ canonical equivalence). `inspector/frontend/src/lib/utils/peaks-fetch.ts:130-142`.
- **`viewPeaks` nested PeakBucket[] branch + null/empty + out-of-range + `isInt8Peaks` discriminator.** `inspector/frontend/src/lib/utils/peaks-view.ts:48-84`.
- **`pack_slim` Int8Array fast-path edge values (-128, -127, 127).** `inspector/frontend/src/lib/utils/peaks-view.ts:100-116`.
- **`audio_meta.chapter_bitrate_kbps_for_reciter`, `chapter_numbers`.** `inspector/services/audio/audio_meta.py:126-238`.
- **`peaks_slim.unpack_slim_envelope` (runtime reader).** `inspector/services/audio/peaks_slim.py:161-203`.
- **`compute_audio_peaks` failure paths** (returncode!=0; stdout<4; `TimeoutExpired`; `FileNotFoundError`; num_samples==0). `qua_shared/peaks_compute.py:74-88`.
- **`pack_slim` ValueError branches.** `qua_shared/peaks_compute.py:124-128`.
- **AudioPort `onError`/`onWaiting`/`onPlaying`.** `inspector/frontend/src/lib/playback/audio-port.ts:565-585`.
- **AudioPort `setPlaybackRate` + `playbackRate` getters propagate to element.** `inspector/frontend/src/lib/playback/audio-port.ts:527-533`.
- **AudioPort `_fanout` subscriber-throw isolation + snapshot iteration.** `inspector/frontend/src/lib/playback/audio-port.ts:684-693`.
- **AudioPort `disableKillSwitch` (dashPort path).** `inspector/frontend/src/lib/playback/audio-port.ts:88-100, 167-170`.
- **AudioPort `prewarm`** (no-op for VBR; no-op when no source/element; CBR triggers `loadCovering(0,0)`; reuse fast-path). `inspector/frontend/src/lib/playback/audio-port.ts:387-411`.
- **AudioPort `loadCovering` fast path 1 (reuse pendingPromise during in-flight swap with covering window).** `inspector/frontend/src/lib/playback/audio-port.ts:341-349`.
- **AudioPort `currentTimeMs()` with no element.** `inspector/frontend/src/lib/playback/audio-port.ts:458-462`.
- **AudioPort `loadCovering` with endMs=Infinity.** `inspector/frontend/src/lib/playback/audio-port.ts:285-293`.
- **`adopt-signal.ts` single-shot semantics.** `inspector/frontend/src/lib/playback/adopt-signal.ts:1-39`.
- **`dashPort` kill-switch-disabled invariant.** `inspector/frontend/src/lib/playback/dash-port.ts:1-25`.
- **AudioRange `setPlaybackRate` callback propagation.** `inspector/frontend/src/lib/playback/audio-range.ts:373-377`.
- **`source.ts` `wrapCbrSrcIfBySurah` + `resolveSegSource`.** `inspector/frontend/src/tabs/segments/utils/playback/source.ts:39-67`.
- **`play-range.ts` (trim/split edit-preview loops).** `inspector/frontend/src/tabs/segments/utils/playback/play-range.ts:76-110`.
- **`keyboard-gate.test.ts` KeyS / Enter (save preview / trim / split / unauthenticated).** `inspector/frontend/src/tabs/segments/utils/keyboard.ts:38-168`.
- **`resolvers.ts` (`nextDisplayedSeg`, `nextSiblingSeg`).** `inspector/frontend/src/tabs/segments/utils/playback/resolvers.ts:20-54`.
- **`row-registry.ts` multi-mount semantics.** `inspector/frontend/src/tabs/segments/utils/playback/row-registry.ts:49-98`.

### Routes / health / public

- **`/api/public/reciters?bucket=publishing` unreachable bucket** (surfaced bug fix + regression test).
- **`/api/public/reciter/<id>` maintainer/admin branch.** `inspector/routes/public/public.py:97-133`.
- **`GET /api/public/activity`** route-layer tests (cursor/limit validation, owner sees `actor_login`, no-store header). `inspector/routes/public/public.py:64-94`.
- **`/healthz` 503 in deployed mode when `db.healthcheck()` fails.** `inspector/services/db/__init__.py:34-39` + `inspector/routes/auth/health.py:70-84`.
- **Bookmarks 502 paths** (all three routes). `inspector/routes/bookmarks.py:40, 62, 79`.
- **Admin releases 502 mappings** (six sites). `inspector/routes/admin/releases.py:92, 298` + `inspector/routes/admin/reviews.py:140, 188, 206, 208`.
- **Webhook 502 orchestrator-exception paths** (ts-job-complete, hf-publish-complete, release-cut-complete). `inspector/routes/webhooks/ts_jobs.py:71, 121, 161`.
- **`hf-publish-complete` and `release-cut-complete` whole routes.** `inspector/routes/webhooks/ts_jobs.py:92-163`.

### Storage / db / sync

- **`pull()` WAL/-shm cleanup, 0o600 perms, stale `.pull.tmp` removal, `_replace_with_retry` retry loop.** `inspector/services/db/sync.py:195-241`.
- **`_safe_err` truncation + redaction.** `inspector/services/db/sync.py:71-73`.
- **`snapshot()` active-txn guard.** `inspector/services/db/sync.py:101-102`.
- **`mark_durable()` no-op paths** (sync disabled; inside `deferred_sync`) + nested `durable_transaction` upload-once. `inspector/services/db/sync.py:322-383`.
- **CAS conflict matrix** (`remote.seq < snap_seq`, `remote.seq == snap_seq` different nonce). `inspector/services/db/sync.py:154-189`.
- **`_read_remote_seq()` graceful-degradation paths.**
- **`_prune_snapshots` swallow-and-log on `list_dir` failure.** `inspector/services/db/sync.py:256-262`.
- **`deferred_sync()` concurrent-task isolation.**
- **Migration runner mid-script failure rollback.** `inspector/services/db/migrate.py:51-68`. Write a deliberately broken NNNN_*.sql, assert user_version stays + logged error.
- **Migration runner non-conforming filename skip.** `inspector/services/db/migrate.py:23, 27-29`.
- **Pre-pull→init_db→migrations integration** with bucket DB at version N, code at version M>N.
- **`FilesystemBackend` direct tests** (atomic-write tmp cleanup; `iter_jsonl` corrupt/blank lines; `list_dir('')`; copy/move/delete dir-vs-file; StorageNotFound).
- **`BucketBackend` `_is_not_found` heuristic + mount-vs-API switching + `write_bytes_direct`/`read_bytes_direct` + `_bucket_upload` cache invalidation.** `inspector/services/storage/hf_bucket.py:181-419`.
- **`_ensure_posix`** rejects absolute / backslash / empty.
- **`get_backend`/`set_backend`/`reset_backend` singleton lifecycle.**
- **`auto_mount()` skip conditions** (pytest, behind proxy, prod-without-opt-in).
- **Per-reciter read-path locks concurrency** (`_history_locks`, `_detailed_locks`). `inspector/services/activity/history_query.py:48-58` + `inspector/services/storage/data_loader.py:24-33`.

### Timestamps / TS routes

- **Most `/api/ts/*` routes** (shard, validation, resource, config, tajweed) + their `timestamps.view_unreleased` capability bypass. `inspector/routes/timestamps/timestamps.py:28-165`.
- **`/api/ts/tajweed` malformed-input branches** (invalid verse_ref, garbage stops). `inspector/routes/timestamps/timestamps.py:139-164`.
- **TS-source loaders / caches / random / translations / tajweed bridges / audio URL.** `inspector/frontend/src/lib/recitation-data/ts-source.ts:103-687`. Currently only `assembleVerseFromShard` family tested.
- **`ts_manifest.invalidate()` clears `_shard_lru`, `_resource_bytes`, audio-manifest sidecar cache.** `inspector/services/reference/timestamps.py:322-340`.
- **Concurrent inside-lock re-check at `timestamps.py:210-243`.** Spawn two threads through `_ensure_built` at same seq.
- **`_build_resource_bytes()` digital_khatt branch + mtime=0 determinism.** `inspector/services/reference/timestamps.py:88-91, 234-238`.

### Validation / classifier

- **Cross-language search-normalize parity** (see codegen-parity gaps above).
- **MISSED_BASMALA_FLAG_MIN_DELETED threshold boundary (N-1 vs N).** `inspector/services/validation/detail.py:423-426`.
- **`_busy_deleted` dedup branch when single seg spans 1:1 and 1:7.** `inspector/services/validation/detail.py:462-467` (untested defensive branch).
- **3 of 8 BRIDGE_RULES never asserted positively** (IDGHAM_BILA_GHUNNAH_NOON, IDGHAM_BILA_GHUNNAH_TANWEEN, IDGHAM_MUTAMATHILAYN). `inspector/services/reference/tajweed.py:40-51`.
- **`normalize_arabic("")` guard.** `inspector/services/activity/search_normalize.py:42-43`.
- **`matches()` negative case.** `inspector/services/activity/search_normalize.py:51-55`.
- **`AUTO_SUPPRESS_CATEGORIES` / `PERSISTS_IGNORE_CATEGORIES` / `CAN_IGNORE_CATEGORIES` derived tuples** assertion against `EXPECTED_MATRIX`. `inspector/services/validation/registry.py:257-265`.
- **`probe_failed_uids=None` vs `set()` distinction.** `inspector/services/validation/classifier.py:225-227, 270-273`.
- **`filter_persistent_ignores` `_all` marker + non-persistent filter.** `inspector/services/validation/registry.py:268-286`.

### Permissions / capabilities

- **`resolve_grants` filters for unknown cap_id / owner_only_fixed / inapplicable cells.** `inspector/services/auth/capabilities.py:69-73`.
- **`capabilities_for` contributor and maintainer tiers.** `inspector/services/auth/capabilities.py:99-102`.
- **Audit emission on `access.grant`/`revoke`/`update`.** Currently no test verifies the audit row lands.

### Spine substrate / migrations

- **Reader connections enforce `PRAGMA query_only=ON`.** `inspector/services/db/connection.py:78-86`. Test that an INSERT through `get_conn()` outside a txn raises sqlite3.OperationalError.
- **`_generation` bumping on `reset()` forces readers to reopen.** `inspector/services/db/connection.py:48, 128-140, 233-243`.
- **`_attach_bucket_dates` integration wrapper.** `inspector/services/reference/public_state.py:217`. End-to-end through `detail()` and `admin_view_reciter()`.
- **Per-slug isolation in `_bucket_dates_for_slug` replay.** `inspector/services/reference/public_state.py:202`.

### Segments editor FE

- **`segments.ts::applyNextState` reducer.** `inspector/frontend/src/tabs/segments/stores/segments.ts:158-217`.
- **`selectors`: `getSegByChapterIndex` / `getAdjacentSegments` primary `s.index === index` branch.** `inspector/frontend/src/tabs/segments/__tests__/normalized-state/selectors.test.ts:14-22`. Fixtures never set `index`, so only the positional fallback is tested.
- **edit.ts bundled-update fan-out optimisation.** `inspector/frontend/src/tabs/segments/stores/edit.ts:46-119`.
- **`derivedEq` prime-on-subscribe, identity skip, multi-subscriber cache, unsubscribe cleanup.** `inspector/frontend/src/lib/utils/derived-eq.ts:28-50`.
- **Rune stores `releasesStore`, `reviewsStore`, `adminDashboard`.** `inspector/frontend/src/lib/stores/releases.svelte.ts:24-68`, `reviews.svelte.ts:37-122`, `tabs/dashboard/stores/admin-dashboard.svelte.ts:19-54`.
- **`current-user` `isAdmin`/`isOwner`, `markGuideReadLocally`, `loadCurrentUser` error path.** `inspector/frontend/src/lib/stores/current-user.ts:60-111`.
- **`segmentsStore`/`chapterStore` derived stores tear-down + subscription identity.**
- **`segValidation` derived stores (`accordionViewActive`, `splitGroupIndex`) + `clearValidation()` atomicity.** `inspector/frontend/src/tabs/segments/stores/validation.ts:21-39`.
- **`shuffle.ts` localStorage load + auto-persist subscribers + `exitLoop()` side-effects.** `inspector/frontend/src/tabs/timestamps/stores/shuffle.ts:19-51, 64-81`.
- **`loop.ts` (lib/playback/loop.ts) — no tests, cross-tab loop authority.**
- **Dashboard stores (`dashboard-state`, `submit-wizard`, `catalog-data`).**
- **Component tests for the validation tab:** ErrorCard, GenericIssueCard, MissingVersesCard, WaslBoundary, GuidesGateModal — zero tests each.
- **`MissingWordsCard` deeper behavior** (auto-fix click, split-group expansion, prev/next sibling rendering, contextchange dispatch, memo invalidation). `inspector/frontend/src/tabs/segments/components/validation/MissingWordsCard.svelte:48-160`.
- **AccordionGuideModal close paths + focus restoration.** `inspector/frontend/src/tabs/segments/components/validation/AccordionGuideModal.svelte:87-134`.
- **AccordionGuideModal record-on-open signed-in path.** `inspector/frontend/src/tabs/segments/components/validation/AccordionGuideModal.svelte:52-68`.
- **Five validation utility modules** (`card-lead-seg`, `conf-class`, `missing-verse-context`, `split-group`, `refresh`) have zero direct coverage.
- **`resolveByUidStrict` merge-redirect fallback.** `inspector/frontend/src/tabs/segments/utils/validation/resolve-issue.ts:49-60`.
- **`filterStaleIssues` merge-redirect rewriting path.** `inspector/frontend/src/tabs/segments/utils/validation/stale.ts:46-69`.
- **`deriveOpIssueDelta`** positive paths (uid dedup, last-op fallback, memoization). `inspector/frontend/src/tabs/segments/utils/validation/classified-issues.ts:87-127`.
- **`isIgnoredFor` three branches.** `classified-issues.ts:45-53`.
- **`SegmentsList.svelte` autoscroll, ResizeObserver anchoring, pinned-editing-row, jump-to-segment, silence-gap render, VIRTUALIZE_THRESHOLD fall-through.**
- **`TimeEdit.svelte` Escape revert, invalid-bounds, blur-outside, ArrowLeft/Right promote, drag-interrupt reactive, greyed-group click.**
- **`CombinationPicker.svelte` keyboard nav, search filter, facet rail toggle, active-claim pinning.**
- **EditAffordancePopover viewport-flip + outside-dismissal + Escape + 6 of 8 viewReason branches.**
- **ClaimConfirmModal busy state + error path + Esc/backdrop + `onClaimed` callback.**
- **SearchInput exported `focus()` + `ariaLabel` prop.**
- **Toggle disabled/busy lock-glyph + spinner + aria-busy + class:on rendering.**
- **ClaimButton anonymous-invisibility + sign-in fallback.**
- **info-doc parser edge cases** (empty lifecycle, malformed inline, mixed runs).
- **OverviewContent.svelte rendering of parsed InfoDoc.**

### Timestamps tab

- **`cycleShuffle` 2→0 wrap + `exitLoop` side-effect.** `inspector/frontend/src/tabs/timestamps/stores/shuffle.ts:64-81`.
- **`findWordAt` boundary semantics.** `inspector/frontend/src/tabs/timestamps/utils/loop-target.ts:16-31`.
- **`applyTsWheelZoom` + `panTsViewBy`.** `inspector/frontend/src/tabs/timestamps/utils/zoom.ts:269-342`.
- **`UnifiedDisplay` letter and phoneme click/dblclick paths.** `inspector/frontend/src/tabs/timestamps/components/UnifiedDisplay.svelte:528-627`.
- **`groupTsValidationVerses` null/empty branches + `cmpVerseRef` edge cases.** `inspector/frontend/src/tabs/timestamps/utils/validation-groups.ts:13-49`.
- **TranslationGlobe / TranslationLangSelect / WordTranslation / TsValidationPanel / TimestampsFooterAnalysis / TimestampsShortcutsGuide — zero component tests.**
- **`manualShuffleRequest` subscriber-fires-on-change behavior.**

### Animation FE

- **Five recitation-animation pure modules.** `chapter-words.ts:45, 133`; `engine/build-structure.ts:47`; `engine/index-cache.ts:22, 45`; `line-window.ts:22`; `config.ts:173`.
- **LineAnimation word-granularity + look-back + clearOnAyahEnd + clearOnOverflow + onSeekToWord + suppressTransition.**
- **RecitationSection / AyahFilmstrip / ControlIcon component tests; `recitation-settings` derived stores + `nowreciting-prefs` localStorage round-trip.**
- **`toArabicNumeral` + `ARABIC_DIGITS`.** `inspector/frontend/src/lib/utils/arabic-text.ts:97`.

### Reduce-motion + a11y (whole-app)

- **No axe-core / jest-axe installed; no test asserts `aria-modal`, focus trap, focus return, Tab cycling.** Modal.svelte has the contracts; tests don't assert them. SearchableSelect has zero tests. ValidationPanel accordion is missing `aria-expanded`/`aria-controls`. AdminDashboardModal and compartments have no tests. ToastHost lacks `aria-live`/`role=status`. Reduced-motion media queries in LineAnimation/AyahFilmstrip have no JS hook + are never asserted.
- **Proposal.** Add `@axe-core/svelte` (or jest-axe equivalent for vitest+happy-dom). Author a shared `assertNoA11yViolations(container)`. Add an "a11y smoke" file mounting top-level shells in default + dark-theme variants. Address the documented structural gaps (aria-expanded/controls/modal/live region) as part of the same PR.

### Cross-system integration

- **claim → save → mark-ready → publish → release route chain.** No HTTP-level test stitches the canonical reviewer journey for a single slug.
- **intake submit → accept → ingest → auto_detect reconcile → AWAITING_REVIEW.** Same gap; tests live in three independent harnesses.
- **released → unlocked-for-revision → re-claim → re-publish cycle.** Uncovered at every layer; `_h_unlocked_for_revision` and `_h_unpublished` have no dedicated tests.
- **`reciter.requested` auto_claim folding through the auto_detect reconciler.** Service-level coverage exists; integration via the reconciler end-to-end does not.
- **discard → undiscard → re-request loop.** Only single-step coverage.

### qua_shared / scripts

- **`_choose_occasion` tie-break on equal mean confidence (earliest wins).** `qua_shared/timestamps_dedup.py:273-278`.
- **`confidence_by_span` edge cases (None / missing fields / empty detailed).** `qua_shared/timestamps_dedup.py:97-118`.
- **`build_segment_shards` `_transitions` rejection branch.** `qua_shared/timestamps_dedup.py:37, 64-65` + `qua_shared/timestamps_shards.py:219-223`.
- **`is_v2` shape discriminator edge cases.** `qua_shared/timestamps_dedup.py:73-85`.
- **`reshape_shard` default-to-by_surah path.** `qua_shared/timestamps_reshape.py:97-104`.
- **`_summary_sentence` previous_version path with only refreshes / only carried / no changes.** `qua_shared/release_changelog.py:84-96`.
- **`render_changelog` `static_refs_changed_keys` branch.** `qua_shared/release_changelog.py:134-138`.
- **`_load_qpc_bytes` bucket-only path (empty staged dir).** `qua_jobs/cut_release.py:640-667`.
- **`_coverage_cell` em-dash fallback.** `qua_shared/release_changelog.py:50-58`.
- **`render_changelog` with empty members list.** `qua_shared/release_changelog.py:99-147`.
- **`_escape_cell` whitespace collapse.** `qua_shared/release_changelog.py:37-40`.
- **Almost all of `scripts/` has no tests** — `scripts/codegen/regen_fe_types.py` (smoke + golden), `scripts/devenv/bootstrap_dev_env.py`, `scripts/devenv/seed_fixtures.py`, `scripts/backfills/backfill_peaks_slim.py`, `scripts/bucket/bucket_sync.py`, `scripts/deploy/upload_inspector.py`, `scripts/diagnostics/bench_storage.py`.
- **`_copy_bucket_content` allowlist + audio_manifest read-path round-trip.** `scripts/devenv/make_fixtures_dataset.py:239`. Confirm exclusions (`audio/`, `peaks/`, `edit_history*.jsonl`).
- **`replace_badges` RuntimeError when markers missing.** `.github/scripts/update_readme_badges.py:176`.
- **`_duration_from_manifest` four raise paths.** `.github/scripts/update_readme_badges.py:52-114`.
- **`build_ts_validation` edge cases** (empty beams, OOB indices, Basmala+/Isti'adha+ prefix, multi-seg-per-verse AND-reduce). `qua_shared/timestamps_pipeline.py:390-404`.

---

## Onboarding doc draft outline (for the follow-up PR that writes `docs/reference/testing.md`)

A new contributor today has no entry point. CLAUDE.md table rows + a 4-line `## Tests` stub in `inspector/README.md:144-150` are the only signposts. `docs/reference/` has 14 subsystem references and zero for testing. The conftest exposes `seed_state` / `seed_role` / `signed_in_client` / `tmp_reciter_dir` / `state_persistence` / `load_fixture` / `load_expected` / `fresh_registry` — all undocumented outside their docstrings. The phase-1 skipIf convention used pervasively under `tabs/segments/__tests__/command/` has no narrative.

**Outline for `docs/reference/testing.md`** (write in follow-up PR; outline lives here):

1. **Scope & quick map.** One-paragraph framing: BE pytest under `inspector/tests/`, FE vitest colocated as `src/**/__tests__/*.test.ts`, shared fixtures under `inspector/tests/fixtures/segments/` (aliased to `@fixtures` in vitest). Pointer table: subsystem → test dir (mirror the docs/reference/README.md table).
2. **Test runners & tools.** BE: pytest with autouse `_substrate_db` (conftest.py:117) — fresh migrated SQLite + sync disabled; teardown resets db_seq + caches. FE: vitest + happy-dom + `@testing-library/svelte` + `@testing-library/user-event`. Shared seeding primitives at conftest.py:153-272 importable from sibling conftests. `FilesystemBackend` test helpers: `tmp_reciter_dir`, `state_persistence`. `signed_in_client` mints a signed cookie. Playwright `npm run test:e2e` — pointer only.
3. **Running tests.** Canonical commands:
   - BE all: `cd inspector && python -m pytest tests/ -v`
   - BE single: `python -m pytest tests/db/test_repo_state.py::test_name -v`
   - BE coverage: `python -m pytest --cov=services --cov=routes --cov-report=term-missing tests/`
   - FE all: `cd inspector/frontend && npm run test`
   - FE single: `npx vitest run src/lib/playback/__tests__/audio-graph.test.ts`
   - FE coverage: `npm run test:coverage`
   - FE typecheck: `npm run check`
   - Note: CI does not gate on coverage thresholds (vitest.config.ts:31 `thresholds: undefined`); coverage is informational.
4. **How to add a test for X subsystem — four walkthroughs.**
   - **State-machine transition rule (BE).** `inspector/tests/db/test_repo_transitions.py` or `tests/services/test_state_request_events.py`. Pattern: `from services.state.state import transition`; use `seed_state` to set FROM state; call `transition(slug, ...)`; assert `ReciterState` + `repo_audit` row. Never mutate state ad-hoc.
   - **HTTP route handler (BE).** Under `tests/routes/test_route_<name>.py`. Pattern: `client, user = signed_in_client(role=...)`; if reading/writing per-reciter bucket content, also request `tmp_reciter_dir` and call `tmp.install(<slug>, <fixture>)` or `tmp.seed_under_review(<slug>, user["hf_user_id"])`; then `client.post(..., json=..., headers={"Origin": "http://localhost"})`. Origin header is required for CSRF on mutating routes. Assert JSON shape + side-effects via `repo_*` reads.
   - **Segments editor command (FE + BE).** FE: `inspector/frontend/src/tabs/segments/__tests__/command/`, build state via `makeSegment`, call `applyCommand(state, command)` directly, assert `result.nextState` + `result.operation`. **Do NOT** use `loadOptional` + `describe.skipIf` for new tests. BE: `inspector/tests/command/` + `tests/persistence/` for JSONL round-trip; use `tmp_reciter_dir`, POST to `/api/save/<slug>`, read via repo / FilesystemBackend.
   - **Frontend component.** `src/lib/components/__tests__/<Name>.test.ts`. Mirror `ClaimButton.test.ts` / `Modal.test.ts`: `render(Component, { props })`; assert via `screen.getByRole`/`getByText`. Svelte 5 components: pass `$bindable` props as plain values. For components reading stores: import the store, set state directly, then render.
5. **Fixture cheatsheet.** Table:

   | Need | Use |
   |---|---|
   | Just a SQLite DB | nothing (autouse `_substrate_db`) |
   | Seed a state row + FK chain | `seed_state(slug, state=, assignee_hf_id=, marked_ready=, ...)` |
   | Seed a member's role | `seed_role(hf_user_id, login=, role=)` |
   | Mint a signed-in test client | `signed_in_client(role=...)` → `(client, user)` |
   | Per-reciter content | `tmp_reciter_dir` — `.install(slug, fixture)`, `.seed_under_review`, `.backend`, `.data_dir` |
   | Per-reciter content WITHOUT fixture | `state_persistence` |
   | Load a JSON fixture | `load_fixture(name)` |
   | Load a baseline expected output | `load_expected(name, kind)` |
   | Validation registry snapshot | `fresh_registry` |
   | Flask client without auth | `flask_client` |

   Rule: don't reach for `tmp_reciter_dir` if all you need is SQLite state — the autouse fixture already gave you that.
6. **Mocking cheatsheet.** See section 6 of this audit — promote the boundary policy table verbatim.
7. **Phase-gate (`describe.skipIf`) policy.** Add only when introducing a test for a module that does not yet exist on `main` and will land in a follow-up commit on the same branch series. Pair with `it.todo('phase-N: <module> not yet present')`. Remove the moment the module lands. A phase-gate older than the PR that introduced it is a smell — audit on every command/* touch.
8. **Schema parity policy (codegen).** After ANY edit under `qua_shared/schemas/`: `python scripts/codegen/regen_fe_types.py` then commit `inspector/frontend/src/lib/types/generated/schemas.ts`. CI's `schema-codegen-check` job enforces. Round-trip tests must construct via Pydantic, never dict literals. Add a round-trip test under `inspector/tests/persistence/` for every new schema.
9. **Coverage how-to.** Commands + interpretation. Note BE branch coverage off by default; FE v8 reports branches. Don't game coverage with assertion-free smoke tests — audit will flag them as `dead-test`.
10. **Conventions.** Test name: `test_<unit>_<scenario>_<expectation>` for BE; `it('does X when Y', ...)` for FE. Co-locate FE tests under `__tests__/`. Co-locate BE tests under the subpackage mirroring the prod tree. One conftest per major tree; promote duplicated seeders up. **Add a one-line row to `docs/reference/README.md`** when this doc lands.
11. **Svelte 4 vs Svelte 5 dispatch pattern.** Brief note: `events: {...}` is for Svelte 4 components with `createEventDispatcher`; pass callbacks as props for Svelte 5 runes components.

---

## Proposed corrections PR plan

Ordered by safety — mechanical first, refactor last. Each item lists estimated touch points.

1. **Delete dead `(deferred)` describe blocks + `it.todo` placeholders.** 15 files under `inspector/frontend/src/tabs/segments/__tests__/`. Pure deletion; no behavior change. ~30 LOC removed per file.
2. **Delete stale `pytest.importorskip` calls.** 9 sites across `tests/classifier/`, `tests/registry/`, `tests/identity/`, `tests/routes/test_route_data.py`. Replace with direct top-level imports.
3. **Drop unused imports** flagged in section 5. ~12 files, 1-5 LOC each.
4. **Delete `_clear_state`, `_stub_state_persist`, `_stub_access_persist`, `_isolate_activity_state` no-op helpers and their call sites.** ~5 files; net deletion.
5. **Sweep phase / refactor narration** from test docstrings + comments per `.claude/rules/comments.md`. ~20 test files + 4-5 production docstrings.
6. **Hoist module-level `INSPECTOR_SESSION_SECRET` setdefault to `tests/conftest.py`** (above any imports of `app`). Delete the 28 duplicates.
7. **Replace `headers={'Origin': 'http://localhost'}` inline with `_HEADERS`** in `test_route_claims.py` (23 sites). Tidy.
8. **Drop redundant `monkeypatch.setitem(_validation.__dict__, ...)` patches** in `test_route_claims.py:70-73, 398-399, 443-444, 468-469` and `test_state_parity.py:199-200`. Single `setattr` suffices.
9. **Move 19 root-level `tests/test_*.py` files to subdirectories** (services/, routes/, utils/). Mechanical rename + git mv. ~19 files.
10. **Rename `test_route_history_peaks_lock.py` → `test_route_history_peaks.py`** and drop the `under_review_for='test-user-1'` from its tests (route is not lock-gated).
11. **Rename `SegmentsList.test.ts` → `virtualization.test.ts`** and update the docstring in `virtualization.ts:8`.
12. **Move `test_ts_validation.py`** from `inspector/tests/scripts/` to `inspector/tests/qua_shared/` or `qua_shared/tests/`.
13. **Move `inspector/tests/smoke/_*_smoke.py` to `scripts/diagnostics/`** and `inspector/tests/parity/snapshot_*.py` to `scripts/codegen/`. Update docstrings + add `tests/smoke/README.md` redirect.
14. **Fix `qua_shared/tests` sys.path bootstrap.** Add `qua_shared/tests/conftest.py` with the path injection at `parents[2]`; delete the seven per-file blocks and `noqa: E402` markers.
15. **Strengthen tautological assertions** identified in section 3 — ~25 sites where the assertion is `A or not A`, or compares two values that can never differ in the test setup, or checks key absence on a structurally absent field. Each is a small rewrite to test the intended invariant.
16. **Replace loose `status_code in (200, 4xx)` tuples** with explicit `== 200` (and dedicated 4xx-path tests where needed). 5 files.
17. **Add `code` envelope assertion** to ~20 4xx route tests per the convention in section 4.
18. **Strip stale fixture noise** — drop `matched_text`/`phonemes_asr` from synthetic fixtures; fix synthetic-classifier `wrap_word_ranges`; rewrite `112-ikhlas.edit_history.jsonl` to canonical v2.
19. **Update CLAUDE.md `extra='allow' → extra='forbid'` for persistence schemas distinction** (line 120). Note the `_extras.py` strip_and_warn behavior.
20. **Promote shared conftest helpers** per section 6 fixture-consolidation table — start with `seed_rows` / `row_spec` / `make_actor` / `_clean_validation`. Migrate call sites file-by-file as the chain lands.
21. **Replace `loadOptional` indirection with static imports** in the affected FE test files; delete `__tests__/helpers/optional.ts` once no callers remain. Drop `__tests__/helpers/xfail.ts` (zero callers).
22. **Strip `as any` casts** from command-test files; type each command literal against the appropriate `SegmentCommand` member.
23. **Replace inline cancelAnimationFrame stub in zoom tests** with `installRafMock()` from `lib/playback/__tests__/raf-harness.ts`.
24. **Audio-range-port: rename `setFileTime` → `setClipTimeMs` and fix the dead-arithmetic docstring** at `__tests__/audio-range-port.test.ts:101-109`.
25. **Snapshot regenerator cleanup:** fix `snapshot_route_baselines.py` to use FilesystemBackend instead of the stale module-attribute-patching loop; fix the `os.environ['INSPECTOR_DATA_DIR']` leak; if the regenerators move to `scripts/codegen/` per (13) this becomes a single pass.
26. **CI: scope autofix `git add` to `src/`** in `.github/workflows/inspector-checks.yml:35-41`; add `.eslintcache` to .gitignore.
27. **CI: gate `inspector-deploy.yml` checks behind `docker-publish.yml`** or split path filters so the workflow doesn't run twice on `main` pushes.
28. **CI: install `inspector/requirements.txt` in `schema-codegen-check`** so pydantic version is pinned to runtime.
29. **Coverage config: drop `*/__init__.py` from omit; drop or document `.bucket/*`; add `src/**/types.ts` to FE exclude; document branch=false asymmetry.**
30. **Rename + tighten test names** where the title overpromises (compat tests, registry parity, claim tests) per section 4. ~10 sites.

Touch-point summary: the corrections PR is roughly 60 files changed, mostly net-deletion (tombstone comments, dead `it.todo`s, stale stubs, duplicate helpers) plus 5-10 small refactors to tighten assertion semantics and move tests into their subsystem directories. No new test files. No new production behavior.

C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\inspector\tests
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\inspector\frontend\src\tabs\segments\__tests__
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\inspector\frontend\src\lib
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\qua_shared\tests
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\inspector\pyproject.toml
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\inspector\frontend\vitest.config.ts
C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\elated-heyrovsky-aa8bb0\.github\workflows\inspector-checks.yml