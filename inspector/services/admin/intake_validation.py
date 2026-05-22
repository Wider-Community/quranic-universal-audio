"""Structural (submit-time) validation for Submit-recitation intake requests.

Cheap, synchronous, no network. Reachability is deferred to the owner-triggered
``intake_probe`` (direct links) and to the offline ingest pipeline (playlist
enumeration + filename 1–114 checks) — see ``docs/reference/admin-dashboard.md``.

``errors`` block submission (HTTP 400); ``warnings`` are advisory (missing
chapters, duplicates, unrecognised playlist host) — the admin adjudicates.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from scripts.lib.schemas import IntakeSubmission, IntakeValidation
from scripts.lib.schemas.intake_requests import SourceLink

from services.state import catalog as catalog_service

TOTAL_CHAPTERS = 114

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Hosts whose playlists/folders the offline ingest can enumerate (yt-dlp / API).
_PLAYLIST_HOSTS = (
    "youtube.com",
    "youtu.be",
    "soundcloud.com",
    "archive.org",
    "drive.google.com",
)


def validate_submission(sub: IntakeSubmission) -> IntakeValidation:
    """Structural validation of one intake submission."""
    errors: list[str] = []
    warnings: list[str] = []

    # --- identity / combination ---
    edits = sub.proposed_edits
    if sub.kind == "new_reciter":
        if not (edits.name_en or "").strip():
            errors.append("English name is required for a new reciter.")
    else:  # existing_reciter_new_combo
        if not (sub.reciter_id or "").strip():
            errors.append("A reciter must be selected for a new combination.")
        elif catalog_service.find_reciter(sub.reciter_id) is None:
            errors.append(f"Unknown reciter: {sub.reciter_id!r}.")

    if not (edits.riwayah or "").strip():
        errors.append("Riwayah is required.")
    if not (edits.style or "").strip():
        errors.append("Style is required.")
    # recording_year bounds (1885–current) are enforced by ProposedEdits at parse.

    # --- source ---
    src = sub.source
    if src.method == "links":
        e, w = _validate_links(src.links)
        errors += e
        warnings += w
    else:  # playlist
        url = (src.playlist_url or "").strip()
        if not url:
            errors.append("A playlist URL is required.")
        elif not _URL_RE.match(url):
            errors.append("Playlist URL must start with http:// or https://.")
        else:
            host = (urlparse(url).hostname or "").lower()
            host = host.removeprefix("www.")
            if not any(host == h or host.endswith("." + h) for h in _PLAYLIST_HOSTS):
                warnings.append(
                    f"Unrecognised playlist host '{host}'. We enumerate playlists "
                    "offline (yt-dlp) — double-check the link is public."
                )

    return IntakeValidation(errors=errors, warnings=warnings)


def _validate_links(links: list[SourceLink]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    counts: dict[int, int] = {}
    malformed = 0
    for ln in links:
        if not _URL_RE.match((ln.url or "").strip()):
            malformed += 1
            continue
        counts[ln.chapter] = counts.get(ln.chapter, 0) + 1

    if malformed:
        errors.append(
            f"{malformed} link(s) are malformed — URLs must start with http:// or https://."
        )

    dups = sorted(c for c, n in counts.items() if n > 1)
    if dups:
        warnings.append(f"Duplicate links for chapter(s): {_compact(dups)}.")

    present = set(counts)
    if not present:
        errors.append("No valid chapter links provided.")
    else:
        missing = [c for c in range(1, TOTAL_CHAPTERS + 1) if c not in present]
        if missing:
            warnings.append(
                f"Missing {len(missing)} of {TOTAL_CHAPTERS} chapters: {_compact(missing)}."
            )

    return errors, warnings


def _compact(nums: list[int]) -> str:
    """Render a sorted int list as compact ranges: ``[1,2,3,7,50,51] → '1–3, 7, 50–51'``."""
    nums = sorted(set(nums))
    if not nums:
        return ""
    parts: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}–{prev}")
    return ", ".join(parts)
