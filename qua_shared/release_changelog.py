"""Render the GitHub-release body from a human-editable Markdown template.

The release preview route and ``qua_jobs/cut_release.py`` both call this
module, so the admin preview and the shipped GitHub body stay in lockstep.
The template lives at ``.github/templates/release_body.md`` and contains only
fixed placeholders; all generated tables and schema snippets are built here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from qua_shared.config_loader import load_template

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-z_]+)\s*}}")
_REQUIRED_BLOCKS = {
    "release_title",
    "asset_table",
    "audio_timestamp_pairing",
    "timestamp_levels",
    "recitation_changes",
    "programmatic_use",
    "staying_up_to_date",
    "reciter_zip_schemas",
    "catalog_manifest_shapes",
    "release_footer",
}


def _neutralise(value: object) -> str:
    """Render any value as text with HTML tags neutralised."""
    s = "" if value is None else str(value)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def _escape_cell(value: object) -> str:
    """Neutralise a value for a GFM table cell."""
    s = _neutralise(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(s.split())


def _reciter_cell(m: dict) -> str:
    en = (m.get("name_en") or "").strip()
    ar = (m.get("name_ar") or "").strip()
    label = f"{en} - {ar}" if en and ar else (en or ar or "(unnamed)")
    return _escape_cell(label)


def _coverage_cell(m: dict) -> str:
    ayahs = m.get("coverage_ayahs")
    if ayahs is not None:
        return f"{int(ayahs):,} ayahs"
    surahs = m.get("coverage_surahs")
    if surahs is not None:
        return f"{int(surahs)} surahs"
    return "-"


def _member_table(members: list[dict]) -> list[str]:
    rows = [
        "| Reciter | Riwayah | Style | Channel | Coverage |",
        "|---|---|---|---|---|",
    ]
    for m in members:
        rows.append(
            f"| {_reciter_cell(m)} | {_escape_cell(m.get('riwayah'))} "
            f"| {_escape_cell(m.get('style'))} | {_escape_cell(m.get('channel'))} "
            f"| {_coverage_cell(m)} |"
        )
    return rows


def _accordion(summary: str, body_lines: list[str]) -> list[str]:
    return [f"<details><summary>{summary}</summary>", "", *body_lines, "</details>"]


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _summary_sentence(
    previous_version: str | None, n_added: int, n_refresh: int, n_carried: int
) -> str:
    if previous_version is None:
        total = n_added + n_refresh + n_carried
        return f"First release: **{total}** recitation{_plural(total)}."
    parts: list[str] = []
    if n_added:
        parts.append(f"adds {n_added}")
    if n_refresh:
        parts.append(f"refreshes {n_refresh}")
    body = ", ".join(parts) if parts else "no membership changes"
    tail = f" ({n_carried} carried)" if n_carried else ""
    return f"{body[0].upper()}{body[1:]}{tail} over {previous_version}."


def _render_template(blocks: Mapping[str, str]) -> str:
    template = load_template("release_body")
    placeholders = set(_PLACEHOLDER_RE.findall(template))
    unknown = placeholders - _REQUIRED_BLOCKS
    missing = _REQUIRED_BLOCKS - placeholders
    if unknown:
        raise ValueError(f"unknown release template placeholders: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing release template placeholders: {sorted(missing)}")

    out = template
    for key in _REQUIRED_BLOCKS:
        out = re.sub(r"{{\s*" + key + r"\s*}}", blocks[key].rstrip(), out)
    return out.rstrip() + "\n"


def _asset_table() -> str:
    return "\n".join(
        [
            "## What to download",
            "",
            "| Asset | What it gives you |",
            "|---|---|",
            "| `manifest.json` | Release index: reciter zips, download URLs, checksums, sizes, coverage, and change type. |",
            "| `catalog.json` | Reciter names, riwayah, style, coverage, audio metadata, and the audio URLs paired with the timestamp data. |",
            "| `<reciter>.zip` | One recitation's verse, word, and letter timestamp files. |",
            "| `shard.py` | Optional helper that splits a large timestamp file into one JSON file per surah. |",
            "| `check_updates.py` | Optional helper that checks the latest release for updates to the reciters you use; add `--sync` to re-download them. |",
            "| `surah_info.json` | Surah names, ayah counts, and word counts. |",
            "| `qpc_hafs.json` | QPC Hafs word reference used by the word and letter indexes. |",
            "| `LICENSE` | CC-BY-4.0 license text. |",
        ]
    )


def _audio_timestamp_pairing() -> str:
    return "\n".join(
        [
            "## How audio and timestamps pair",
            "",
            "`catalog.json` contains the audio URLs for each recitation. Timestamp values are relative to that matching source audio.",
            "",
            'For a surah-based recitation, a value like `"100:1": [0, 2831]` means ayah 100:1 starts at `0 ms` and ends at `2831 ms` in the matching surah audio.',
        ]
    )


def _timestamp_levels() -> str:
    return "\n".join(
        [
            "## Timestamp levels",
            "",
            "| File | Use it when you need | Why it is separate |",
            "|---|---|---|",
            "| `verse_timestamps.json.gz` | verse playback or verse clips | smallest download |",
            "| `word_timestamps.json.gz` | word highlighting | faster than loading letters when you only need words |",
            "| `letter_timestamps.json.gz` | fine-grained alignment | full detail for research and advanced UI |",
            "",
            "The files are split and gzipped for storage, speed, and network efficiency. Download only the level you need.",
            "",
            "Use `shard.py` when your app prefers per-surah files locally:",
            "",
            "```bash",
            "python shard.py word_timestamps.json.gz --out-dir per_surah",
            "```",
        ]
    )


def _recitation_changes(
    *, previous_version: str | None, added: list[dict], refreshed: list[dict], carried: int
) -> str:
    out: list[str] = [
        "## Recitations",
        "",
        _summary_sentence(previous_version, len(added), len(refreshed), carried),
        "",
    ]
    if added:
        out.extend(
            _accordion(
                f"Added recitations - {len(added)}",
                _member_table(added),
            )
        )
        out.append("")
    if refreshed:
        out.extend(
            _accordion(
                f"Refreshed recitations - {len(refreshed)}",
                _member_table(refreshed),
            )
        )
        out.append("")
    if carried:
        out.append(f"{carried} carried / unchanged.")
    return "\n".join(out).rstrip()


def _programmatic_use() -> str:
    return "\n".join(
        [
            "## Programmatic use",
            "",
            "Read `manifest.json`, choose a reciter from `recitations`, download its `zip_url`, and verify the zip with `sha256`.",
            "",
            "Use `catalog.json` when you need display names, coverage, audio metadata, or the source audio URLs that the timestamps refer to.",
        ]
    )


def _staying_up_to_date() -> str:
    return "\n".join(
        [
            "## Staying up to date",
            "",
            "We occasionally fix issues or batch-refresh a reciter's timestamps with an improved alignment model, so a reciter you already use can change in a later release. Two ways to keep track:",
            "",
            "- **All releases** - click **Watch -> Custom -> Releases** at the top of the GitHub repository. GitHub emails you on every release, and the notes above always list which reciters were added or refreshed.",
            "- **Only the reciters you use** - run `check_updates.py` against the `manifest.json` you downloaded. It exits non-zero when any of your reciters changed, so a scheduled GitHub Action or CI job notifies you automatically; add `--sync` to also re-download the changed zips.",
            "",
            "```bash",
            "# report which of your reciters changed (exit 1 if any)",
            "python check_updates.py manifest.json --reciters mishary_rashid_al_afasy_mp3quran",
            "",
            "# or keep your local copy in sync automatically",
            "python check_updates.py manifest.json --sync",
            "```",
        ]
    )


def _reciter_zip_schemas() -> str:
    return "\n".join(
        [
            "<details><summary>Reciter zip schemas</summary>",
            "",
            "Each reciter zip contains `manifest.json`, `catalog.json`, and three timestamp files.",
            "",
            "```ts",
            'type VerseKey = "surah:ayah";',
            "type Ms = number;",
            "type Word = [word_idx: number, start_ms: Ms, end_ms: Ms];",
            "type Letter = [word_idx: number, char: string, start_ms: Ms, end_ms: Ms];",
            "",
            'type VerseTimestamps = { _meta: Meta & { tier: "verse" }, [verse: VerseKey]: [Ms, Ms] };',
            'type WordTimestamps = { _meta: Meta & { tier: "word" }, [verse: VerseKey]: [[Ms, Ms], Word[]] };',
            'type LetterTimestamps = { _meta: Meta & { tier: "letter" }, [verse: VerseKey]: [[Ms, Ms], Word[], Letter[]] };',
            "```",
            "",
            "Small example:",
            "",
            "```json",
            "{",
            '  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "verse", "verse_count": 6236},',
            '  "1:1": [0, 2831]',
            "}",
            "```",
            "",
            "```json",
            "{",
            '  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "word", "verse_count": 6236},',
            '  "1:1": [[0, 2831], [[1, 70, 1550], [2, 1550, 2790]]]',
            "}",
            "```",
            "",
            "```json",
            "{",
            '  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "letter", "verse_count": 6236},',
            '  "1:1": [[0, 2831], [[1, 70, 1550]], [[1, "ب", 70, 180]]]',
            "}",
            "```",
            "",
            "</details>",
        ]
    )


def _catalog_manifest_shapes() -> str:
    return "\n".join(
        [
            "<details><summary>Catalog and manifest schemas</summary>",
            "",
            "```ts",
            "type ReleaseManifest = {",
            "  schema_version: 1;",
            "  release_version: string;",
            "  recitation_count: number;",
            "  static_refs: Record<string, { sha256: string; bytes: number }>;",
            "  recitations: Record<string, {",
            "    zip: string;",
            "    zip_url: string;",
            "    sha256: string;",
            "    bytes: number;",
            "    coverage_ayahs: number;",
            '    change_kind: "added" | "refresh" | "unchanged";',
            "  }>;",
            '  license: "CC-BY-4.0";',
            "};",
            "```",
            "",
            "```json",
            "{",
            '  "release_version": "v0.1.0",',
            '  "recitation_count": 9,',
            '  "recitations": {',
            '    "example_reciter": {"zip": "example_reciter.zip", "coverage_ayahs": 6236, "change_kind": "added"}',
            "  }",
            "}",
            "```",
            "",
            '`catalog.json` is `{ "schema_version": 1, "recitations": [ReciterCatalog, ...] }`.',
            "",
            "</details>",
        ]
    )


def _release_footer(*, license_id: str, owner: str, repo: str, hf_dataset: str) -> str:
    out = [f"**License:** {license_id}"]
    if owner and repo:
        out.append(f"- Repository: https://github.com/{owner}/{repo}")
    if hf_dataset:
        out.append(f"- HF dataset: https://huggingface.co/datasets/{hf_dataset}")
    return "\n".join(out)


def render_changelog(
    *,
    version: str,
    previous_version: str | None,
    release_date: str,
    members: list[dict],
    static_refs_changed_keys: tuple[str, ...] | list[str] = (),
    owner: str = "",
    repo: str = "",
    hf_dataset: str = "",
    license_id: str = "CC-BY-4.0",
) -> str:
    """Return the full release body markdown."""
    added = [m for m in members if m.get("change_kind") == "added"]
    refreshed = [m for m in members if m.get("change_kind") == "refresh"]
    carried = sum(1 for m in members if m.get("change_kind") == "unchanged")
    return _render_template(
        {
            "release_title": f"# {release_date}",
            "asset_table": _asset_table(),
            "audio_timestamp_pairing": _audio_timestamp_pairing(),
            "timestamp_levels": _timestamp_levels(),
            "recitation_changes": _recitation_changes(
                previous_version=previous_version,
                added=added,
                refreshed=refreshed,
                carried=carried,
            ),
            "programmatic_use": _programmatic_use(),
            "staying_up_to_date": _staying_up_to_date(),
            "reciter_zip_schemas": _reciter_zip_schemas(),
            "catalog_manifest_shapes": _catalog_manifest_shapes(),
            "release_footer": _release_footer(
                license_id=license_id,
                owner=owner,
                repo=repo,
                hf_dataset=hf_dataset,
            ),
        }
    )
