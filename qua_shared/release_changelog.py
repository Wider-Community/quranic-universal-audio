"""Render the GitHub-release body (the "changelog") — single source of truth.

Shared by the two callers that must agree on what a release looks like:
  - ``qua_jobs/cut_release.py`` — the body actually POSTed to GitHub by the cut HF Job.
  - ``inspector/routes/admin/releases.py`` — the dry-run preview the operator sees in the
    cut modal before launching.

Both pass the same member-dict shape (display names + coverage already resolved by the
caller) so the preview is faithful to what ships. This module is stdlib-only and pure —
no DB, no I/O — and NEVER emits slugs; callers resolve riwayah/style/channel display names
from the vocab tables. ``operator_note`` is treated as untrusted free text: HTML-significant
characters are neutralised so a note can't break out of its blockquote or inject markup.
"""

from __future__ import annotations

# (asset name, human description). Folded into one collapsible "Schemas" accordion.
_TIER_SCHEMAS: list[tuple[str, str]] = [
    (
        "verse_timestamps.json.gz",
        'Tier 1. Positional `"surah:ayah": [start_ms, end_ms]`. '
        "Times are source-relative milliseconds.",
    ),
    (
        "word_timestamps.json.gz",
        'Tier 2. Positional `"surah:ayah": [[start, end], [[widx, start, end], ...]]`. '
        "Source-relative ms.",
    ),
    (
        "letter_timestamps.json.gz",
        'Tier 3. Positional `"surah:ayah": [[start, end], [words], '
        "[[widx, char, start, end], ...]]`. Source-relative ms.",
    ),
]


def _neutralise(value: object) -> str:
    """Render any value as text with HTML tags neutralised (``<``/``>`` → entities)."""
    s = "" if value is None else str(value)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def _escape_cell(value: object) -> str:
    """Neutralise a value for a GFM table cell — tags, pipes, backslashes, newlines."""
    s = _neutralise(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(s.split())


def _reciter_cell(m: dict) -> str:
    en = (m.get("name_en") or "").strip()
    ar = (m.get("name_ar") or "").strip()
    label = f"{en} — {ar}" if en and ar else (en or ar or "(unnamed)")
    return _escape_cell(label)


def _coverage_cell(m: dict) -> str:
    """Exact ayah count when known (cut time), else surah count (DB-only preview)."""
    ayahs = m.get("coverage_ayahs")
    if ayahs is not None:
        return f"{int(ayahs):,} ayahs"
    surahs = m.get("coverage_surahs")
    if surahs is not None:
        return f"{int(surahs)} surahs"
    return "—"


def _member_table(members: list[dict]) -> list[str]:
    rows = [
        "| Reciter | Riwāyah | Style | Channel | Coverage |",
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
    # Blank line after <summary> is required for GitHub to render a table/list inside.
    return [f"<details><summary>{summary}</summary>", "", *body_lines, "</details>", ""]


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _summary_sentence(
    previous_version: str | None, n_added: int, n_refresh: int, n_carried: int
) -> str:
    total = n_added + n_refresh + n_carried
    if previous_version is None:
        return f"First release — **{total}** recitation{_plural(total)}."
    parts: list[str] = []
    if n_added:
        parts.append(f"adds {n_added}")
    if n_refresh:
        parts.append(f"refreshes {n_refresh}")
    body = ", ".join(parts) if parts else "no membership changes"
    tail = f" ({n_carried} carried)" if n_carried else ""
    return f"{body[0].upper()}{body[1:]}{tail} over {previous_version}."


def render_changelog(
    *,
    version: str,
    previous_version: str | None,
    release_date: str,
    members: list[dict],
    static_refs_changed_keys: tuple[str, ...] | list[str] = (),
    operator_note: str | None = None,
    owner: str = "",
    repo: str = "",
    hf_dataset: str = "",
    license_id: str = "CC-BY-4.0",
) -> str:
    """Return the full release body markdown.

    ``members`` entries carry display names + change_kind + coverage; see the module
    docstring for the contract. ``release_date`` is a pre-formatted human string.
    """
    added = [m for m in members if m.get("change_kind") == "added"]
    refreshed = [m for m in members if m.get("change_kind") == "refresh"]
    carried = sum(1 for m in members if m.get("change_kind") == "unchanged")

    out: list[str] = [f"# {version} · {release_date}", ""]
    out.append(_summary_sentence(previous_version, len(added), len(refreshed), carried))
    out.append("")

    if operator_note and operator_note.strip():
        out.extend(f"> {_neutralise(line)}" for line in operator_note.strip().splitlines())
        out.append("")

    if added:
        out.extend(
            _accordion(
                f"➕ Added — {len(added)} recitation{_plural(len(added))}", _member_table(added)
            )
        )
    if refreshed:
        out.extend(
            _accordion(
                f"↻ Refreshed — {len(refreshed)} recitation{_plural(len(refreshed))}",
                _member_table(refreshed),
            )
        )
    if carried:
        out.extend([f"{carried} carried / unchanged.", ""])

    schema_lines = [f"- `{name}` — {desc}" for name, desc in _TIER_SCHEMAS]
    refs = ", ".join(
        f"`{key}` ({'refreshed' if key in static_refs_changed_keys else 'unchanged'})"
        for key in ("surah_info.json", "qpc_hafs.json")
    )
    schema_lines += ["", f"Static references: {refs}."]
    out.extend(_accordion("📐 Schemas", schema_lines))

    out.append(f"**License:** {license_id}")
    if owner and repo:
        out.append(f"- Repository: https://github.com/{owner}/{repo}")
    if hf_dataset:
        out.append(f"- HF dataset: https://huggingface.co/datasets/{hf_dataset}")

    return "\n".join(out).rstrip() + "\n"
