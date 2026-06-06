"""Tests for the shared release-changelog renderer.

``qua_shared/release_changelog.py`` is the single source of truth for the GH
release body, used by both the cut HF Job and the Inspector cut-modal preview.
These guard the format contract: title first, asset table first, display names
only (no slugs), concise guide copy, and two collapsed schema sections.
"""

from __future__ import annotations

from qua_shared.release_changelog import render_changelog


def _member(
    name_en,
    *,
    change_kind="added",
    riwayah="Hafs A'n Assem",
    style="Murattal",
    channel="Tarteel CDN",
    coverage_surahs=114,
    coverage_ayahs=None,
    name_ar="فلان",
):
    return {
        "name_en": name_en,
        "name_ar": name_ar,
        "riwayah": riwayah,
        "style": style,
        "channel": channel,
        "change_kind": change_kind,
        "coverage_surahs": coverage_surahs,
        "coverage_ayahs": coverage_ayahs,
    }


def test_first_release_added_only():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="2026-06-03",
        members=[_member("Abdulbasit Abdulsamad"), _member("Saud Al-Shuraim")],
        owner="Wider-Community",
        repo="quranic-universal-audio",
        hf_dataset="hetchyy/quranic-universal-ayahs",
    )
    assert md.startswith("# 2026-06-03\n\n## What to download")
    assert "This release publishes" not in md
    assert (
        "| `catalog.json` | Reciter names, riwayah, style, coverage, audio metadata, and the audio URLs paired with the timestamp data. |"
        in md
    )
    assert "release_schemas.json" not in md
    assert "First release: **2** recitations." in md
    assert "<details><summary>Added recitations - 2</summary>" in md
    assert "Abdulbasit Abdulsamad" in md
    # No refreshed / carried sections on a clean first cut.
    assert "Refreshed" not in md
    assert "carried" not in md


def test_display_names_no_slugs():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="2026-06-03",
        members=[_member("Abdulbasit Abdulsamad")],
    )
    assert "Hafs A'n Assem" in md and "Tarteel CDN" in md
    # The slug forms must never leak into the human-facing body.
    for slug in ("hafs_an_asim", "_tarteel", "murattal"):
        assert slug not in md


def test_added_refreshed_and_carried():
    members = [
        _member("New One", change_kind="added"),
        _member("Updated One", change_kind="refresh"),
        _member("Stable One", change_kind="unchanged"),
        _member("Stable Two", change_kind="unchanged"),
    ]
    md = render_changelog(
        version="v0.2.0",
        previous_version="v0.1.0",
        release_date="2026-07-01",
        members=members,
    )
    assert "<details><summary>Added recitations - 1</summary>" in md
    assert "<details><summary>Refreshed recitations - 1</summary>" in md
    assert "2 carried / unchanged." in md
    assert "Adds 1, refreshes 1 (2 carried) over v0.1.0." in md


def test_coverage_cell_ayahs_then_surahs():
    md_ayahs = render_changelog(
        version="v1.0.0",
        previous_version=None,
        release_date="d",
        members=[_member("R", coverage_ayahs=6236, coverage_surahs=114)],
    )
    assert "6,236 ayahs" in md_ayahs
    md_surahs = render_changelog(
        version="v1.0.0",
        previous_version=None,
        release_date="d",
        members=[_member("R", coverage_ayahs=None, coverage_surahs=114)],
    )
    assert "114 surahs" in md_surahs and "ayahs" not in md_surahs.split("Reciter zip schemas")[0]


def test_audio_pairing_and_timestamp_layers_are_explained():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="d",
        members=[_member("R")],
    )
    assert "`catalog.json` contains the audio URLs for each recitation" in md
    assert "every timestamp value is milliseconds relative to that matching source audio." in md
    assert "storage, speed, and network efficiency" in md
    assert "Use `shard.py` when your app prefers per-surah files locally" in md
    assert '"1:1": [0, 2831]' in md
    # the worked example spans multiple words + letters (not a single ب letter)
    assert "ٱللَّهِ" in md
    assert '"س"' in md and '"ا"' in md
    assert "loops back or re-recites" in md


def test_staying_up_to_date_section_and_asset_row():
    md = render_changelog(
        version="v0.3.0",
        previous_version="v0.2.0",
        release_date="d",
        members=[_member("R", change_kind="refresh")],
    )
    assert "## Staying up to date" in md
    assert "Watch -> Custom -> Releases" in md
    assert "python check_updates.py manifest.json --sync" in md
    # asset-table row advertises the helper
    assert "`check_updates.py` |" in md


def test_license_inline_and_links():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="d",
        members=[_member("R")],
        owner="Wider-Community",
        repo="quranic-universal-audio",
        hf_dataset="hetchyy/quranic-universal-ayahs",
        license_id="CC-BY-4.0",
    )
    assert "**License:** CC-BY-4.0" in md
    assert "https://github.com/Wider-Community/quranic-universal-audio" in md
    assert "https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs" in md


def test_table_cell_pipe_escaped():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="d",
        members=[_member("A | B")],
    )
    assert "A \\| B" in md


def test_schema_sections_are_collapsed():
    md = render_changelog(
        version="v0.1.0",
        previous_version=None,
        release_date="d",
        members=[_member("R")],
    )
    assert "<details><summary>Reciter zip schemas</summary>" in md
    assert "<details><summary>Catalog and manifest schemas</summary>" in md
    assert "type VerseTimestamps" in md
    assert '"tier": "verse"' in md
    assert '"tier": "word"' in md
    assert '"tier": "letter"' in md
    assert "type ReleaseManifest" in md
