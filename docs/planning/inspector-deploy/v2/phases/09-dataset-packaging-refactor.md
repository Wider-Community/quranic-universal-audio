# Phase 7 — Dataset packaging refactor

> Switch the HF dataset's audio packaging from "re-encode every ayah to 128 kbps MP3" to a quality-preserving pipeline. Stops the unnecessary lossy re-encode pass. Adds per-ayah source metadata so consumers can filter. Independent of Inspector deploy — runs after the catalog is stable.

**Status:** not started
**Depends on:** Phase 1 (Foundation) — needs `<bucket>/catalog/reciter_catalog.json` deliveries to carry source `codec` / `bitrate_kbps_nominal` / `sample_rate_hz` / `channels` / `bitrate_mode`. The dataset packaging script reads these per-delivery fields to decide what to do.
**Blocks:** —

## Goal

The public HF dataset (`hetchyy/quranic-universal-ayahs` and successors) stops re-encoding source audio to a normalized 128 kbps MP3. Instead, packaging preserves source audio quality losslessly and surfaces source codec / bitrate / sample rate in the dataset row metadata so downstream consumers can filter. `by_ayah` source deliveries skip slicing entirely (already per-ayah). The catalog's audio metadata becomes the truthful upstream signal of what was in the dataset, not just what the source was.

## Deliverables

- [ ] `.github/scripts/build_reciter.py::download_and_slice` — switch the export from `format="mp3", bitrate="128k"` to a quality-preserving format (see "Options" below; default = FLAC)
- [ ] `.github/scripts/build_reciter.py` — add per-ayah row metadata columns: `source_codec`, `source_container`, `source_bitrate_kbps`, `source_bitrate_mode`, `source_sample_rate_hz`, `source_channels`. Pulled from `<bucket>/catalog/reciter_catalog.json` delivery row at packaging time.
- [ ] `.github/scripts/build_reciter.py` — `by_ayah` deliveries: skip MFA slicing, copy URL bytes as-is into the dataset row (still re-encoded only if the new format differs from source MP3; ideally pass-through)
- [ ] `.github/workflows/sync-dataset.yml` — adjusted for the new format + metadata columns; new dataset version published as a separate revision (no in-place clobber)
- [ ] `docs/hf_dataset_card.md` — updated for the new format / row schema + a migration note for prior dataset consumers
- [ ] One end-to-end re-package of a representative reciter as smoke test (suggestion: Mahmoud Khalil Al-Husary, since the catalog has both his 64k and 128k qdc deliveries; the new pipeline should preserve both at their native bitrates)
- [ ] Migration plan documented: existing dataset slices already published — either re-extract from source URLs to the new format, or freeze the old version and ship the new one as v2

## Options (pick one before starting)

**A. FLAC (recommended).** Single decision, future-proof. Lossless from source. Dataset grows ~3–5× vs 128k MP3 but HF storage scales fine. Modern ML datasets (Common Voice, LibriSpeech) use FLAC for the same reason.

**B. Stream-copy MP3 (`ffmpeg -c copy`)** for MP3 sources, fall back to re-encode for non-MP3. Preserves source bitrate exactly. Cuts are frame-aligned (~26 ms granularity at 128k) — fine for ayah-scale slicing since MFA timestamps are themselves ±10–30 ms.

**C. Adaptive: FLAC for ≤96k sources, stream-copy for ≥128k MP3 sources.** Best fidelity without bloat. More code paths.

Recommended: **A** for simplicity. Storage is cheap; lossless gives downstream consumers full flexibility.

## Out of scope

- Loudness normalization
- Per-ayah audio enhancement / denoising / noise removal
- Resampling to 16 kHz mono for ASR (consumer's choice, not packaging's)
- Replacing the MFA alignment pipeline itself (this phase changes packaging, not alignment)
- Adding the missing `by_ayah` row-field probe data — that's a separate `bulk_probe.py` re-run job
- Migrating consumers of the old dataset format — out-of-scope; downstream concern
- A `v3` dataset schema beyond the new metadata columns

## Acceptance criteria

- [ ] FLAC (or chosen-format) output retains source resolution: ffprobe confirms sample rate and channel count match the catalog's row.
- [ ] Per-row metadata: a sample ayah row from the new dataset has all six `source_*` fields populated, values match `<bucket>/catalog/reciter_catalog.json` for that delivery.
- [ ] `by_ayah` sources: an ayah row in the new dataset matches the source manifest URL's byte content (modulo container-level re-encode only if format differs).
- [ ] MFA alignment quality is unchanged (the pipeline reads source directly, not the dataset; this is a sanity check, not a code change).
- [ ] One reciter end-to-end: download Husary 64k source → slice with MFA → emit FLAC → upload to a test dataset → verify with `datasets.load_dataset(...)` returns FLAC bytes.
- [ ] Dataset card reflects the new format + row schema accurately.

## Verification

```bash
# Re-package one reciter, verify FLAC slices
python .github/scripts/build_reciter.py \
  --reciter mahmoud_khalil_al_husary \
  --emit-format flac \
  --dry-run

# Spot-check a slice
ffprobe -v error -show_format -show_streams -of json out/001001.flac
# Expect: codec=flac, sample_rate matches catalog, channels match catalog

# Compare slice fidelity vs source
ffmpeg -i source.mp3 -ss 1.2 -to 6.4 -c copy ref.mp3
ffmpeg -i out/001001.flac -c:a mp3 -b:a 128k cmp.mp3
# Manual A/B if needed
```

## Risks

- **Storage growth.** FLAC dataset is ~3–5× larger than 128k MP3. HF dataset storage handles it but the cost line item grows.
- **Consumer breakage.** Downstream code expecting MP3 bytes will break. Mitigate via the dataset card migration note + a parallel v1/v2 publication for one cycle.
- **`by_ayah` URL accessibility.** Pass-through requires source URLs to stay reachable. If a source CDN dies, the dataset row breaks. Mitigation: download once into the bucket on first packaging; future-proof against source disappearance.
- **Per-row metadata join correctness.** Reading from the catalog at packaging time means the catalog must be authoritative. Drift between catalog and packaging script = wrong metadata in rows. Mitigate: packaging script asserts `audio_manifest_checksum` (sidecar) matches at packaging time.

## Reference

- [`docs/reference/reciter-catalog.md`](../../../../reference/reciter-catalog.md) §5 — describes catalog-as-source-of-truth for audio metadata; dataset is downstream
- [`.github/scripts/build_reciter.py:417`](../../../../../.github/scripts/build_reciter.py) — current re-encode call site
- [`.github/workflows/sync-dataset.yml`](../../../../../.github/workflows/sync-dataset.yml) — the workflow that triggers packaging
