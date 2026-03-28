"""
Reciter Request Space — Gradio form + FastAPI API for submitting
reciter segmentation requests and viewing pipeline status.

Deployed as HF Space: hetchyy/Quran-reciter-requests
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from base64 import b64decode
from pathlib import Path

import yaml

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import gradio as gr
import httpx
import pycountry

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_APP_DIR = Path(__file__).resolve().parent


def _load_app_config(name: str) -> dict:
    with open(_APP_DIR / "config" / f"{name}.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_app_template(name: str) -> str:
    return (_APP_DIR / "templates" / f"{name}.md").read_text(encoding="utf-8")


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
REPO_OWNER = "Wider-Community"
REPO_NAME = "quranic-universal-audio"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("request_app")

# ---------------------------------------------------------------------------
# Cache with TTL
# ---------------------------------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 600  # 10 minutes


def _get_cached(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry["ts"] < CACHE_TTL:
            return entry["data"]
    return None


def _set_cached(key, data):
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time()}


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------
def _gh_headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _gh_get(path, params=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/{path}"
    r = httpx.get(url, headers=_gh_headers(), params=params, timeout=30)
    if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(r.headers.get("X-RateLimit-Reset", 0)) - int(time.time())
        wait = min(max(reset, 1), 5)
        logger.warning(f"GitHub rate limited, waiting {wait}s")
        time.sleep(wait)
        r = httpx.get(url, headers=_gh_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _gh_get_raw(path):
    """Fetch raw file content from the default branch."""
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{path}"
    r = httpx.get(url, headers=_gh_headers(), timeout=30)
    if r.status_code == 403:
        time.sleep(2)
        r = httpx.get(url, headers=_gh_headers(), timeout=30)
    r.raise_for_status()
    return r.text


def _verify_github_user(username):
    """Check if a GitHub username exists. Returns True/False/None (API error)."""
    try:
        r = httpx.get(
            f"https://api.github.com/users/{username}",
            headers=_gh_headers(), timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return None  # Don't block on API errors


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _notion_create_page(properties):
    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    r = httpx.post(url, headers=_notion_headers(), json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def _repo_segments_exist(slug):
    """Check if segment data exists in the repo for this reciter."""
    try:
        _gh_get(f"contents/data/recitation_segments/{slug}/segments.json")
        return True
    except Exception:
        return False


def _notion_slug_exists(slug):
    """Check if a Notion page with this slug exists in the database."""
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        return None  # Can't check — treat as unknown
    try:
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        body = {
            "filter": {
                "property": "Slug",
                "rich_text": {"equals": slug},
            },
            "page_size": 1,
        }
        r = httpx.post(url, headers=_notion_headers(), json=body, timeout=15)
        r.raise_for_status()
        return len(r.json().get("results", [])) > 0
    except Exception as e:
        logger.warning(f"Notion slug check failed: {e}")
        return None  # Unknown — don't block on Notion failure


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def _is_check(val):
    """Check if a table cell value is a positive marker (✓, ✓✓, Y)."""
    v = val.strip()
    return v in ("Y", "✓", "✓✓")


def _parse_processed_reciters(md_text):
    """Parse the Aligned Reciters table from RECITERS.md.

    Table columns: Reciter | Style | Source | Granularity | Coverage |
                   Segmented | Manually Validated | Timestamped
    """
    processed = []
    in_table = False
    for line in md_text.split("\n"):
        if "| Reciter" in line and "Coverage" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 8:
                processed.append({
                    "name": cols[0],
                    "style": cols[1].lower().replace(" ", "_") if cols[1] else "unknown",
                    "coverage": cols[4],
                    "segmented": _is_check(cols[5]),
                    "validated": _is_check(cols[6]),
                    "timestamped": _is_check(cols[7]),
                })
        elif in_table and not line.strip().startswith("|"):
            break
    return processed


def _slug_from_name(name):
    """Convert display name to snake_case slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch_processed_reciters():
    """Fetch processed reciters with their VAD parameters."""
    cached = _get_cached("processed")
    if cached is not None:
        return cached

    try:
        md = _gh_get_raw("data/RECITERS.md")
        processed = _parse_processed_reciters(md)

        # Fetch VAD params from segments.json _meta for each
        for rec in processed:
            slug = _slug_from_name(rec["name"])
            rec["slug"] = slug
            try:
                # Get first 500 bytes of segments.json via API (base64)
                content_data = _gh_get(
                    f"contents/data/recitation_segments/{slug}/segments.json"
                )
                raw = b64decode(content_data["content"]).decode("utf-8", errors="replace")
                # Parse just the _meta from the first line
                first_line_end = raw.find("\n")
                if first_line_end == -1:
                    first_line_end = len(raw)
                meta_obj = json.loads(raw[:first_line_end])
                if "_meta" in meta_obj:
                    meta = meta_obj["_meta"]
                else:
                    meta = meta_obj
                rec["min_silence_ms"] = meta.get("min_silence_ms", "?")
                rec["audio_source"] = meta.get("audio_source", "?")
            except Exception:
                rec["min_silence_ms"] = "?"
                rec["audio_source"] = "?"

        _set_cached("processed", processed)
        return processed
    except Exception as e:
        logger.error(f"Failed to fetch processed reciters: {e}")
        return []


def _fetch_reciters_index():
    """Fetch the pre-computed reciters index from GitHub (single API call)."""
    cached = _get_cached("reciters_index")
    if cached is not None:
        return cached
    try:
        raw = _gh_get_raw("data/reciters_index.json")
        data = json.loads(raw)
        _set_cached("reciters_index", data)
        return data
    except Exception as e:
        logger.error(f"Failed to fetch reciters index: {e}")
        return []


def fetch_available_reciters():
    """Fetch available (unprocessed) reciters from the pre-computed index."""
    cached = _get_cached("available")
    if cached is not None:
        return cached

    try:
        index = _fetch_reciters_index()
        processed = fetch_processed_reciters()
        processed_slugs = {r["slug"] for r in processed}

        # Fetch open request issues to mark pending
        pending = {}
        try:
            issues = _gh_get("issues", params={
                "labels": "request",
                "state": "open",
                "per_page": 100,
            })
            for iss in issues:
                body = iss.get("body", "")
                slug_match = re.search(r"\*\*Slug:\*\*\s*(\S+)", body)
                if slug_match:
                    pending[slug_match.group(1)] = iss["html_url"]
        except Exception:
            pass

        reciters = []
        seen = set()
        for r in index:
            slug = r["slug"]
            if slug in processed_slugs or slug in seen:
                continue
            seen.add(slug)
            source_path = f"{r['audio_cat']}/{r['source']}"
            reciters.append({
                "slug": slug,
                "name": r["name_en"],
                "source": source_path,
                "riwayah": r["riwayah"],
                "style": r["style"],
                "country": r.get("country", "unknown"),
                "has_pending_request": slug in pending,
                "pending_issue_url": pending.get(slug, ""),
            })

        _set_cached("available", reciters)
        return reciters
    except Exception as e:
        logger.error(f"Failed to fetch available reciters: {e}")
        return []


def _build_issue_pr_lookup(prs, issues):
    """Build {issue_number: pr_html_url} from PR list.

    Strategy 1: Parse 'Closes #N' / 'Fixes #N' / 'Resolves #N' from PR body.
    Strategy 2: Match branch name feat/add-segments-{slug} to issue slug.
    """
    lookup = {}
    for pr in prs:
        body = pr.get("body", "") or ""
        for m in re.finditer(
            r"(?:Closes|Fixes|Resolves)\s+#(\d+)", body, re.IGNORECASE
        ):
            lookup[int(m.group(1))] = pr["html_url"]

    # Strategy 2: branch name matching
    slug_to_issue = {}
    for iss in issues:
        if iss.get("reciter_slug"):
            slug_to_issue[iss["reciter_slug"]] = iss["issue_number"]
    for pr in prs:
        branch = pr.get("head", {}).get("ref", "")
        m = re.match(r"feat/add-segments-(.+)", branch)
        if m:
            branch_slug = m.group(1).replace("-", "_")
            issue_num = slug_to_issue.get(branch_slug)
            if issue_num and issue_num not in lookup:
                lookup[issue_num] = pr["html_url"]

    return lookup


def fetch_request_issues():
    """Fetch all request issues from GitHub, with linked PR URLs."""
    cached = _get_cached("requests")
    if cached is not None:
        return cached

    try:
        # Fetch both open and closed issues
        all_issues = []
        for state in ["open", "closed"]:
            issues = _gh_get("issues", params={
                "labels": "request",
                "state": state,
                "per_page": 100,
            })
            all_issues.extend(issues)

        # Build initial result list (without pr_url yet)
        result = []
        for iss in all_issues:
            labels = [l["name"] for l in iss.get("labels", [])]
            status = "pending"
            for l in labels:
                if l.startswith("status:"):
                    status = l.split(":", 1)[1]

            # Extract slug from body
            body = iss.get("body", "")
            slug_match = re.search(r"\*\*Slug:\*\*\s*(\S+)", body)
            slug = slug_match.group(1) if slug_match else ""

            result.append({
                "issue_number": iss["number"],
                "title": iss["title"],
                "reciter_slug": slug,
                "status": status,
                "created_at": iss["created_at"][:10],
                "updated_at": iss["updated_at"][:10],
                "url": iss["html_url"],
                "pr_url": "",
            })

        # Fetch PRs to build issue→PR lookup
        try:
            all_prs = []
            for pr_state in ["open", "closed"]:
                prs = _gh_get("pulls", params={
                    "state": pr_state,
                    "per_page": 100,
                })
                all_prs.extend(prs)
            pr_lookup = _build_issue_pr_lookup(all_prs, result)
            for r in result:
                r["pr_url"] = pr_lookup.get(r["issue_number"], "")
        except Exception as e:
            logger.warning(f"Failed to fetch PRs for lookup: {e}")

        _set_cached("requests", result)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch request issues: {e}")
        return []


# ---------------------------------------------------------------------------
# Submit request
# ---------------------------------------------------------------------------
# Load riwayah data from riwayat.json (ground truth)
_RIWAYAH_SLUG_TO_NAME: dict[str, str] = {}
_RIWAYAH_NAME_TO_SLUG: dict[str, str] = {}
RIWAYAT: list[str] = []


def _load_riwayat():
    """Fetch riwayat.json from GitHub and build slug↔name mappings."""
    global _RIWAYAH_SLUG_TO_NAME, _RIWAYAH_NAME_TO_SLUG, RIWAYAT
    if RIWAYAT:
        return
    try:
        raw = _gh_get_raw("data/riwayat.json")
        data = json.loads(raw)
        _RIWAYAH_SLUG_TO_NAME = {r["slug"]: r["name"] for r in data}
        _RIWAYAH_NAME_TO_SLUG = {r["name"]: r["slug"] for r in data}
        RIWAYAT = [r["name"] for r in data]
    except Exception as e:
        logger.error(f"Failed to load riwayat.json: {e}")
        # Fallback so the form still renders
        RIWAYAT = ["Hafs A'n Assem"]
        _RIWAYAH_SLUG_TO_NAME = {"hafs_an_asim": "Hafs A'n Assem"}
        _RIWAYAH_NAME_TO_SLUG = {"Hafs A'n Assem": "hafs_an_asim"}


def _riwayah_slug_to_name(slug: str) -> str:
    """Convert riwayah slug to display name."""
    _load_riwayat()
    return _RIWAYAH_SLUG_TO_NAME.get(slug, slug.replace("_", " ").title())

_form_data = _load_app_config("form_data")
_msgs = _load_app_config("messages")

REQUEST_TYPES = _form_data["request_types"]
STYLE_CHOICES = _form_data["style_choices"]
_STYLE_DISPLAY_TO_SLUG = _form_data["style_slug_map"]
_STYLE_SLUG_TO_DISPLAY = {v: k for k, v in _STYLE_DISPLAY_TO_SLUG.items()}

AUDIO_CATEGORIES = ["By Surah", "By Ayah"]
_AUDIO_CAT_TO_SLUG = {"By Surah": "by_surah", "By Ayah": "by_ayah"}

# Build country list from pycountry (ISO 3166), preferring common names.
# Add aliases for values used in existing manifests that differ from ISO.
_COUNTRY_ALIASES = _form_data["country_aliases"]
COUNTRIES = ["unknown"] + sorted(
    _COUNTRY_ALIASES.get(getattr(c, "common_name", c.name), getattr(c, "common_name", c.name))
    for c in pycountry.countries
) + ["Other"]


def submit_request(
    reciter_slug, reciter_name, audio_source,
    request_type, riwayah, style, country,
    min_silence_ms,
    requester_name, requester_email, notes,
    github_username="",
):
    """Create GitHub Issue + Notion row for a new reciter request."""
    # Validate
    if not reciter_slug or not reciter_name:
        return _msgs["errors"]["no_reciter"]
    if not requester_name or not requester_name.strip():
        return _msgs["errors"]["no_name"]
    if not requester_email or not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", requester_email.strip()):
        return _msgs["errors"]["invalid_email"]
    if not request_type:
        return _msgs["errors"]["no_request_type"]
    if not riwayah:
        return _msgs["errors"]["no_riwayah"]
    _load_riwayat()
    if RIWAYAT and riwayah not in _RIWAYAH_NAME_TO_SLUG and riwayah not in _RIWAYAH_SLUG_TO_NAME:
        return _msgs["errors"]["unknown_riwayah"].format(riwayah=riwayah)
    if min_silence_ms is None or min_silence_ms == "":
        return _msgs["errors"]["no_min_silence"]
    try:
        min_silence_ms = int(min_silence_ms)
    except (ValueError, TypeError):
        return _msgs["errors"]["invalid_min_silence_type"]
    if not (100 <= min_silence_ms <= 2000):
        return _msgs["errors"]["min_silence_range"]
    request_type = request_type or "New reciter"
    style = style or "Unknown"
    if style not in STYLE_CHOICES:
        style = "Unknown"
    country = country or "unknown"
    if country not in COUNTRIES:
        country = "unknown"

    # Verify GitHub username if provided
    github_username = (github_username or "").strip().lstrip("@")
    if github_username:
        user_exists = _verify_github_user(github_username)
        if user_exists is False:
            return _msgs["errors"]["github_user_not_found"].format(github_username=github_username)

    # Check for duplicate requests
    if request_type == "New reciter":
        try:
            issues = _gh_get("issues", params={
                "labels": "request",
                "state": "all",
                "per_page": 100,
            })
            for iss in issues:
                body = iss.get("body", "")
                if f"**Slug:** {reciter_slug}" in body:
                    url = iss["html_url"]
                    state = iss.get("state", "open")
                    if state == "open":
                        return _load_app_template("duplicate-open").format(url=url)
                    # Closed issue — check if data was cleaned up
                    has_segments = _repo_segments_exist(reciter_slug)
                    has_notion = _notion_slug_exists(reciter_slug)
                    if has_segments or has_notion:
                        return _load_app_template("duplicate-closed").format(url=url)
                    # Data cleaned up — allow fresh request
                    logger.info(
                        f"Closed issue found for {reciter_slug} but data removed "
                        f"(segments={has_segments}, notion={has_notion}) — "
                        f"allowing new request"
                    )
                    break
        except Exception as e:
            logger.warning(f"Duplicate check failed: {e}")

    # Generate requester_id (no PII in public issue)
    requester_id = hashlib.sha256(
        requester_email.strip().lower().encode()
    ).hexdigest()[:8]

    # Build title prefix
    title_prefix = (
        _msgs["title_prefixes"]["new_reciter"]
        if request_type == "New reciter"
        else _msgs["title_prefixes"]["re_align"]
    )

    # Create GitHub Issue
    github_line = f"**GitHub:** @{github_username}\n" if github_username else ""
    notes_line = f"**Notes:** {notes.strip()}\n" if notes and notes.strip() else ""
    issue_body = _load_app_template("issue-body").format(
        request_type=request_type,
        reciter_name=reciter_name,
        slug=reciter_slug,
        audio_source=audio_source,
        riwayah=riwayah,
        style=style,
        country=country,
        min_silence_ms=min_silence_ms,
        requester_id=requester_id,
        github_line=github_line,
        notes_line=notes_line,
    )

    try:
        issue_json = {
            "title": f"{title_prefix} {reciter_name}",
            "body": issue_body,
            "labels": _msgs["issue_labels"]["new_reciter"],
        }
        if github_username:
            issue_json["assignees"] = [github_username]
        issue_resp = httpx.post(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues",
            headers=_gh_headers(),
            json=issue_json,
            timeout=30,
        )
        issue_resp.raise_for_status()
        issue_data = issue_resp.json()
        issue_url = issue_data["html_url"]
        issue_number = issue_data["number"]
    except Exception as e:
        logger.error(f"GitHub issue creation failed: {e}")
        return f"Error: Failed to create request. Please try again later.\n\n{e}"

    # Create Notion page (best-effort)
    try:
        _notion_create_page({
            "Requester Name": {"title": [{"text": {"content": requester_name.strip()}}]},
            "Email": {"email": requester_email.strip().lower()},
            "Reciter": {"rich_text": [{"text": {"content": reciter_name}}]},
            "Slug": {"rich_text": [{"text": {"content": reciter_slug}}]},
            "Audio Source": {"rich_text": [{"text": {"content": audio_source}}]},
            "Request Type": {"select": {"name": request_type}},
            "Riwayah": {"rich_text": [{"text": {"content": riwayah}}]},
            "Style": {"rich_text": [{"text": {"content": style}}]},
            "Country": {"rich_text": [{"text": {"content": country}}]},
            "Min Silence": {"number": min_silence_ms},
            "GitHub Username": {"rich_text": [{"text": {"content": github_username[:100]}}]},
            "Status": {"select": {"name": "Pending"}},
            "GitHub Issue": {"url": issue_url},
            "Issue Number": {"number": issue_number},
            "Notes": {"rich_text": [{"text": {"content": (notes or "").strip()[:2000]}}]},
        })
    except Exception as e:
        logger.warning(f"Notion page creation failed (issue was created): {e}")

    # Invalidate caches
    _set_cached("requests", None)
    _set_cached("available", None)

    return _load_app_template("success").format(issue_url=issue_url)


# ---------------------------------------------------------------------------
# Gradio UI helpers
# ---------------------------------------------------------------------------
def _reciter_label(name, riwayah="hafs_an_asim", style="murattal"):
    """Build a display label with qualifiers for non-default riwayah/style."""
    qualifiers = []
    if riwayah and riwayah != "hafs_an_asim":
        qualifiers.append(_riwayah_slug_to_name(riwayah))
    if style and style not in ("murattal", "unknown"):
        qualifiers.append(_STYLE_SLUG_TO_DISPLAY.get(style, style.title()))
    if qualifiers:
        return f"{name} — {', '.join(qualifiers)}"
    return name


def get_reciter_choices(request_type="New reciter", audio_cat="By Surah"):
    """Return (display_label, value_json) tuples for the dropdown."""
    if request_type == "Re-align":
        processed = fetch_processed_reciters()
        choices = []
        for r in sorted(processed, key=lambda x: x["name"]):
            if r.get("validated"):
                continue  # Already manually validated — no need to re-align
            label = r["name"]
            choices.append((label, json.dumps({
                "slug": r["slug"],
                "name": r["name"],
                "source": r.get("audio_source", ""),
                "riwayah": "",
                "style": r.get("style", ""),
                "country": "",
            })))
        if not choices:
            choices = [(_msgs["ui"]["no_realign_reciters"], "")]
        return choices
    else:
        cat_slug = _AUDIO_CAT_TO_SLUG.get(audio_cat, "by_surah")
        reciters = fetch_available_reciters()
        choices = []
        for r in sorted(reciters, key=lambda x: x["name"]):
            if r["has_pending_request"]:
                continue
            # Filter by audio category (source path starts with by_surah/ or by_ayah/)
            if not r["source"].startswith(cat_slug):
                continue
            label = _reciter_label(r["name"], r.get("riwayah", ""), r.get("style", ""))
            choices.append((label, json.dumps({
                "slug": r["slug"],
                "name": r["name"],
                "source": r["source"],
                "riwayah": r.get("riwayah", ""),
                "style": r.get("style", ""),
                "country": r.get("country", ""),
            })))
        return choices


def update_on_request_type(request_type):
    """Called when request type changes — swap reciter choices, toggle audio cat."""
    if request_type == "Re-align":
        choices = get_reciter_choices("Re-align")
        return gr.Dropdown(choices=choices, value=None), gr.Dropdown(visible=False)
    else:
        choices = get_reciter_choices("New reciter", "By Surah")
        return (
            gr.Dropdown(choices=choices, value=None),
            gr.Dropdown(value="By Surah", visible=True),
        )


def update_on_audio_cat(audio_cat, request_type):
    """Called when audio category changes — filter reciter choices."""
    choices = get_reciter_choices(request_type, audio_cat)
    return gr.Dropdown(choices=choices, value=None)


def on_reciter_selected(reciter_json):
    """Auto-fill riwayah, style, and country when a reciter is selected."""
    empty = gr.Dropdown(), gr.Dropdown(), gr.Dropdown()
    if not reciter_json:
        return empty
    try:
        info = json.loads(reciter_json)
        riwayah_slug = info.get("riwayah", "")
        style_slug = info.get("style", "")
        country = info.get("country", "")

        riwayah_update = (
            gr.Dropdown(value=_riwayah_slug_to_name(riwayah_slug))
            if riwayah_slug else gr.Dropdown()
        )
        style_update = (
            gr.Dropdown(value=_STYLE_SLUG_TO_DISPLAY.get(style_slug, ""))
            if style_slug else gr.Dropdown()
        )
        country_update = (
            gr.Dropdown(value=country)
            if country and country != "unknown" else gr.Dropdown()
        )
        return riwayah_update, style_update, country_update
    except (json.JSONDecodeError, TypeError):
        return empty


def get_requests_markdown():
    """Return markdown table of request issues."""
    requests = fetch_request_issues()
    if not requests:
        return _msgs["ui"]["no_requests"]
    lines = ["| Reciter | Status | Submitted | Updated | Issue | PR |",
             "|---------|--------|-----------|---------|-------|------|"]
    for r in requests:
        name = r["title"].replace("[request] ", "").replace("[re-align] ", "")
        issue_link = f"[#{r['issue_number']}]({r['url']})"
        pr_link = f"[View]({r['pr_url']})" if r.get("pr_url") else ""
        lines.append(
            f"| {name} | {r['status']} | {r['created_at']} "
            f"| {r['updated_at']} | {issue_link} | {pr_link} |"
        )
    return "\n".join(lines)


def get_processed_markdown():
    """Return markdown table of processed reciters."""
    processed = fetch_processed_reciters()
    if not processed:
        return _msgs["ui"]["no_data"]
    lines = ["| Reciter | Source | Min Silence |",
             "|---------|--------|-------------|"]
    for r in processed:
        lines.append(
            f"| {r['name']} | {r.get('audio_source', '?')} "
            f"| {r.get('min_silence_ms', '?')}ms |"
        )
    return "\n".join(lines)


def handle_submit(reciter_json, request_type, riwayah, style, country,
                   min_silence, name, email, github_username, notes):
    """Handle form submission from Gradio UI."""
    if not reciter_json:
        return _msgs["errors"]["no_reciter"]

    try:
        info = json.loads(reciter_json)
    except (json.JSONDecodeError, TypeError):
        return _msgs["errors"]["invalid_reciter_selection"]

    return submit_request(
        reciter_slug=info["slug"],
        reciter_name=info["name"],
        audio_source=info["source"],
        request_type=request_type,
        riwayah=riwayah,
        style=style,
        country=country,
        min_silence_ms=min_silence,
        requester_name=name,
        requester_email=email,
        notes=notes,
        github_username=github_username,
    )


def fetch_guide():
    """Fetch the requesting-a-reciter guide from GitHub."""
    cached = _get_cached("guide")
    if cached is not None:
        return cached
    try:
        md = _gh_get_raw("docs/requesting-a-reciter.md")
        # Convert relative links (../) to absolute GitHub links
        base = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/tree/main"
        md = re.sub(
            r'\]\(\.\./([^)]+)\)',
            lambda m: f']({base}/{m.group(1)})',
            md,
        )
        _set_cached("guide", md)
        return md
    except Exception as e:
        logger.error(f"Failed to fetch guide: {e}")
        return _msgs["ui"]["guide_fallback"]


def refresh_dashboard():
    """Clear caches and refresh dashboard data."""
    _set_cached("requests", None)
    _set_cached("processed", None)
    return get_requests_markdown(), get_processed_markdown()


# ---------------------------------------------------------------------------
# Gradio App
# ---------------------------------------------------------------------------

with gr.Blocks(title="Reciter Requests") as demo:
    gr.Markdown("# Quran Reciter Segmentation Requests")
    gr.Markdown(
        "Submit a request to have a new reciter processed through the "
        "alignment pipeline. Track the status of all requests below.\n\n"
        "Don't see your reciter in the dropdown? "
        "[Add one](https://github.com/Wider-Community/quranic-universal-audio/blob/main/docs/adding-a-reciter.md)."
    )

    with gr.Tabs():
        # ── Tab 1: Submit Request ─────────────────────────────────────
        with gr.Tab("Submit Request"):
            with gr.Row():
                with gr.Column(scale=2):
                    request_type_dd = gr.Dropdown(
                        choices=REQUEST_TYPES,
                        value="New reciter",
                        label="Request Type",
                        info="New reciter = first-time processing. "
                             "Re-align = re-run with different parameters.",
                    )
                    audio_cat_dd = gr.Dropdown(
                        choices=AUDIO_CATEGORIES,
                        value="By Surah",
                        label="Audio Source Type",
                        info="By Surah = full-chapter audio files. "
                             "By Ayah = per-verse audio files.",
                    )
                    reciter_dd = gr.Dropdown(
                        choices=[],
                        label="Reciter",
                        info="Select a reciter to request segmentation for. "
                             "Already-processed and pending reciters are excluded.",
                        filterable=True,
                    )
                    riwayah_dd = gr.Dropdown(
                        choices=[],
                        label="Riwayah",
                        info="Auto-filled from the reciter's manifest. "
                             "Change only if you know the reciter uses a different reading.",
                    )
                    style_dd = gr.Dropdown(
                        choices=STYLE_CHOICES,
                        label="Style",
                        info="Recitation style. Auto-filled from manifest.",
                    )
                    country_dd = gr.Dropdown(
                        choices=COUNTRIES,
                        label="Country",
                        filterable=True,
                        info="Reciter's country of origin. Auto-filled from manifest.",
                    )
                    min_silence = gr.Number(
                        value=None, label="Min Silence (ms)",
                        info="Required. Check the parameter reference table for guidance. "
                             "Murattal: 300–600ms, Mujawwad: 600–1200ms.",
                        minimum=100, maximum=2000, step=50,
                    )
                    req_name = gr.Textbox(
                        label="Your Name",
                        placeholder="Enter your name",
                    )
                    req_email = gr.Textbox(
                        label="Your Email",
                        placeholder="For notification when processing is complete",
                        type="email",
                    )
                    req_github = gr.Textbox(
                        label="GitHub Username (optional)",
                        placeholder="For write access to the review PR",
                    )
                    req_notes = gr.Textbox(
                        label="Notes (optional)",
                        placeholder="Any additional notes about this reciter",
                        lines=2,
                    )
                    submit_btn = gr.Button("Submit Request", variant="primary")
                    result_box = gr.Textbox(
                        label="Result",
                        interactive=False,
                        lines=4,
                    )

                with gr.Column(scale=1):
                    gr.Markdown("### Parameter Reference")
                    gr.Markdown(
                        "These are the VAD parameters used for already-processed "
                        "reciters. Use them as a guide for your suggestion."
                    )
                    ref_table = gr.Markdown(
                        value="*Loading...*",
                    )

            request_type_dd.change(
                fn=update_on_request_type,
                inputs=[request_type_dd],
                outputs=[reciter_dd, audio_cat_dd],
            )

            audio_cat_dd.change(
                fn=update_on_audio_cat,
                inputs=[audio_cat_dd, request_type_dd],
                outputs=[reciter_dd],
            )

            reciter_dd.change(
                fn=on_reciter_selected,
                inputs=[reciter_dd],
                outputs=[riwayah_dd, style_dd, country_dd],
            )

            submit_btn.click(
                fn=handle_submit,
                inputs=[reciter_dd, request_type_dd, riwayah_dd, style_dd,
                        country_dd, min_silence, req_name, req_email,
                        req_github, req_notes],
                outputs=result_box,
            )

        # ── Tab 2: Dashboard ──────────────────────────────────────────
        with gr.Tab("Dashboard"):
            refresh_btn = gr.Button("Refresh", variant="secondary")

            gr.Markdown("### Request Status")
            gr.Markdown(
                "All reciter segmentation requests and their current pipeline status."
            )
            requests_table = gr.Markdown(value="*Loading...*")

            gr.Markdown("### Completed Reciters")
            gr.Markdown(
                "Reciters that have been fully processed with their VAD parameters."
            )
            processed_table = gr.Markdown(value="*Loading...*")

            refresh_btn.click(
                fn=refresh_dashboard,
                outputs=[requests_table, processed_table],
            )

        # ── Tab 3: Guide ──────────────────────────────────────────────
        with gr.Tab("Guide") as guide_tab:
            guide_md = gr.Markdown(value="*Loading guide...*")

            guide_tab.select(
                fn=fetch_guide,
                outputs=guide_md,
            )

    # ── Deferred initial data load (runs after server starts) ────────
    def _load_initial_data():
        """Fetch all startup data in one callback so the server starts fast."""
        _load_riwayat()
        reciter_choices = get_reciter_choices()
        proc_md = get_processed_markdown()
        req_md = get_requests_markdown()
        return (
            gr.Dropdown(choices=reciter_choices),
            gr.Dropdown(choices=RIWAYAT),
            gr.Dropdown(choices=STYLE_CHOICES),
            gr.Dropdown(choices=COUNTRIES),
            gr.Dropdown(choices=AUDIO_CATEGORIES, value="By Surah"),
            proc_md,
            req_md,
            proc_md,
        )

    demo.load(
        fn=_load_initial_data,
        outputs=[reciter_dd, riwayah_dd, style_dd, country_dd, audio_cat_dd,
                 ref_table, requests_table, processed_table],
    )


# ---------------------------------------------------------------------------
# Custom API routes (mounted onto Gradio's app after launch)
# ---------------------------------------------------------------------------
_api_routes = FastAPI()
_api_routes.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@_api_routes.post("/request")
async def api_request(request: Request):
    """API endpoint for Inspector form submissions."""
    req = await request.json()
    result = submit_request(
        reciter_slug=req.get("reciter_slug", ""),
        reciter_name=req.get("reciter_name", ""),
        audio_source=req.get("audio_source", ""),
        request_type=req.get("request_type", "New reciter"),
        riwayah=req.get("riwayah", ""),
        style=req.get("style", "Unknown"),
        country=req.get("country", "unknown"),
        min_silence_ms=req.get("min_silence_ms"),
        requester_name=req.get("requester_name", ""),
        requester_email=req.get("requester_email", ""),
        notes=req.get("notes", ""),
        github_username=req.get("github_username", ""),
    )

    if result.startswith("Error:"):
        return JSONResponse({"status": "error", "message": result}, status_code=400)
    elif "already has a pending request" in result:
        url_match = re.search(r"(https://\S+)", result)
        return JSONResponse({
            "status": "duplicate",
            "message": result,
            "existing_issue_url": url_match.group(1) if url_match else "",
        }, status_code=409)
    else:
        url_match = re.search(r"(https://\S+)", result)
        return JSONResponse({
            "status": "created",
            "message": result,
            "issue_url": url_match.group(1) if url_match else "",
        }, status_code=201)


@_api_routes.get("/reciters")
async def api_reciters():
    """List available (unprocessed) reciters."""
    return {"reciters": fetch_available_reciters()}


@_api_routes.get("/processed")
async def api_processed():
    """List processed reciters with VAD parameters."""
    return {"reciters": fetch_processed_reciters()}


@_api_routes.get("/requests")
async def api_requests():
    """List all request issues."""
    return {"requests": fetch_request_issues()}


@_api_routes.get("/guide")
async def api_guide():
    """Fetch the requesting-a-reciter guide markdown."""
    return {"markdown": fetch_guide()}


# ---------------------------------------------------------------------------
# Launch — let Gradio own the server, mount custom routes after
# ---------------------------------------------------------------------------
demo.launch(
    server_name="0.0.0.0",
    server_port=7860,
    prevent_thread_lock=True,
    ssr_mode=False,
)
demo.app.mount("/api", _api_routes)

# Keep process alive (Gradio server runs in a background thread)
threading.Event().wait()
