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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import gradio as gr
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
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
    r.raise_for_status()
    return r.json()


def _gh_get_raw(path):
    """Fetch raw file content from the default branch."""
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{path}"
    r = httpx.get(url, headers=_gh_headers(), timeout=30)
    r.raise_for_status()
    return r.text


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


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def _is_check(val):
    """Check if a table cell value is a positive marker (✓, ✓✓, Y)."""
    v = val.strip()
    return v in ("Y", "✓", "✓✓")


def _parse_processed_reciters(md_text):
    """Parse the Processed Reciters table from RECITERS.md."""
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
            if len(cols) >= 4:
                processed.append({
                    "name": cols[0],
                    "coverage": cols[1],
                    "segmented": _is_check(cols[2]),
                    "validated": _is_check(cols[3]) if len(cols) > 3 else False,
                    "timestamped": _is_check(cols[4]) if len(cols) > 4 else False,
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


def fetch_available_reciters():
    """Fetch available (unprocessed) reciters from GitHub."""
    cached = _get_cached("available")
    if cached is not None:
        return cached

    try:
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
                # Extract slug from issue body
                body = iss.get("body", "")
                slug_match = re.search(r"\*\*Slug:\*\*\s*(\S+)", body)
                if slug_match:
                    pending[slug_match.group(1)] = iss["html_url"]
        except Exception:
            pass

        reciters = []
        for category in ["by_surah", "by_ayah"]:
            try:
                sources = _gh_get(f"contents/data/audio/{category}")
            except Exception:
                continue
            for source_entry in sources:
                if source_entry["type"] != "dir":
                    continue
                source_name = source_entry["name"]
                try:
                    files = _gh_get(
                        f"contents/data/audio/{category}/{source_name}"
                    )
                except Exception:
                    continue
                for f in files:
                    if not f["name"].endswith(".json"):
                        continue
                    slug = f["name"].replace(".json", "")
                    if slug in processed_slugs:
                        continue

                    # Try to get display name from _meta
                    display_name = slug.replace("_", " ").title()
                    source_path = f"{category}/{source_name}"

                    reciters.append({
                        "slug": slug,
                        "name": display_name,
                        "source": source_path,
                        "has_pending_request": slug in pending,
                        "pending_issue_url": pending.get(slug, ""),
                    })

        # Deduplicate by slug (keep first occurrence)
        seen = set()
        unique = []
        for r in reciters:
            if r["slug"] not in seen:
                seen.add(r["slug"])
                unique.append(r)

        _set_cached("available", unique)
        return unique
    except Exception as e:
        logger.error(f"Failed to fetch available reciters: {e}")
        return []


def fetch_request_issues():
    """Fetch all request issues from GitHub."""
    cached = _get_cached("requests")
    if cached is not None:
        return cached

    try:
        # Fetch both open and closed
        all_issues = []
        for state in ["open", "closed"]:
            issues = _gh_get("issues", params={
                "labels": "request",
                "state": state,
                "per_page": 100,
            })
            all_issues.extend(issues)

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
            })

        _set_cached("requests", result)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch request issues: {e}")
        return []


# ---------------------------------------------------------------------------
# Submit request
# ---------------------------------------------------------------------------
RIWAYAT = [
    # Asim
    "Hafs an Asim",
    "Shubah an Asim",
    # Nafi
    "Warsh an Nafi",
    "Qalun an Nafi",
    # Abu Amr
    "Al-Duri an Abu Amr",
    "Al-Susi an Abu Amr",
    # Ibn Amir
    "Hisham an Ibn Amir",
    "Ibn Dhakwan an Ibn Amir",
    # Ibn Kathir
    "Al-Bazzi an Ibn Kathir",
    "Qunbul an Ibn Kathir",
    # Hamzah
    "Khalaf an Hamzah",
    "Khallad an Hamzah",
    # Al-Kisai
    "Al-Layth an Al-Kisai",
    "Al-Duri an Al-Kisai",
    # Abu Jafar
    "Isa Ibn Wardan an Abu Jafar",
    "Ibn Jummaz an Abu Jafar",
    # Yaqub
    "Ruways an Yaqub",
    "Rawh an Yaqub",
    # Khalaf
    "Ishaq an Khalaf",
    "Idris an Khalaf",
]

REQUEST_TYPES = ["New reciter", "Re-align"]


def submit_request(
    reciter_slug, reciter_name, audio_source,
    request_type, riwayah, min_silence_ms,
    requester_name, requester_email, notes
):
    """Create GitHub Issue + Notion row for a new reciter request."""
    # Validate
    if not reciter_slug or not reciter_name:
        return "Error: Please select a reciter."
    if not requester_name or not requester_name.strip():
        return "Error: Please enter your name."
    if not requester_email or "@" not in requester_email:
        return "Error: Please enter a valid email address."
    if not request_type:
        return "Error: Please select a request type."
    if not riwayah:
        return "Error: Please select a riwayah."

    min_silence_ms = int(min_silence_ms or 500)
    request_type = request_type or "New reciter"
    riwayah = riwayah or "Hafs an Asim"

    # Check for duplicate (only for "New reciter" — re-align is allowed)
    if request_type == "New reciter":
        try:
            issues = _gh_get("issues", params={
                "labels": "request",
                "state": "open",
                "per_page": 100,
            })
            for iss in issues:
                body = iss.get("body", "")
                if f"**Slug:** {reciter_slug}" in body:
                    url = iss["html_url"]
                    return (
                        f"This reciter already has a pending request.\n\n"
                        f"Track status: {url}"
                    )
        except Exception as e:
            logger.warning(f"Duplicate check failed: {e}")

    # Generate requester_id (no PII in public issue)
    requester_id = hashlib.sha256(
        requester_email.strip().lower().encode()
    ).hexdigest()[:8]

    # Build title prefix
    title_prefix = "[request]" if request_type == "New reciter" else "[re-align]"

    # Create GitHub Issue
    issue_body = (
        f"**Request Type:** {request_type}\n"
        f"**Reciter:** {reciter_name}\n"
        f"**Slug:** {reciter_slug}\n"
        f"**Audio Source:** {audio_source}\n"
        f"**Riwayah:** {riwayah}\n"
        f"**Suggested Min Silence:** {min_silence_ms}ms\n"
        f"**Requester:** {requester_id}\n"
    )
    if notes and notes.strip():
        issue_body += f"**Notes:** {notes.strip()}\n"

    try:
        issue_resp = httpx.post(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues",
            headers=_gh_headers(),
            json={
                "title": f"{title_prefix} {reciter_name}",
                "body": issue_body,
                "labels": ["request", "status:pending"],
            },
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

    return (
        f"Request submitted successfully!\n\n"
        f"Track status: {issue_url}\n\n"
        f"You'll receive email updates when the status changes."
    )


# ---------------------------------------------------------------------------
# Gradio UI helpers
# ---------------------------------------------------------------------------
def get_reciter_choices(request_type="New reciter"):
    """Return (display_label, value_json) tuples for the dropdown."""
    if request_type == "Re-align":
        processed = fetch_processed_reciters()
        choices = []
        for r in sorted(processed, key=lambda x: x["name"]):
            if r.get("validated"):
                continue  # Already manually validated — no need to re-align
            label = f"{r['name']} ({r.get('audio_source', '?')})"
            choices.append((label, json.dumps({
                "slug": r["slug"],
                "name": r["name"],
                "source": r.get("audio_source", ""),
            })))
        return choices
    else:
        reciters = fetch_available_reciters()
        choices = []
        for r in sorted(reciters, key=lambda x: (x["source"], x["name"])):
            if r["has_pending_request"]:
                continue
            label = f"{r['name']} ({r['source']})"
            choices.append((label, json.dumps({
                "slug": r["slug"],
                "name": r["name"],
                "source": r["source"],
            })))
        return choices


def update_reciter_choices(request_type):
    """Called when request type changes — swap reciter dropdown choices."""
    choices = get_reciter_choices(request_type)
    return gr.update(choices=choices, value=None)


def get_requests_markdown():
    """Return markdown table of request issues."""
    requests = fetch_request_issues()
    if not requests:
        return "*No requests yet.*"
    lines = ["| Reciter | Status | Submitted | Updated | Link |",
             "|---------|--------|-----------|---------|------|"]
    for r in requests:
        name = r["title"].replace("[request] ", "")
        url = r["url"]
        lines.append(
            f"| {name} | {r['status']} | {r['created_at']} "
            f"| {r['updated_at']} | [View]({url}) |"
        )
    return "\n".join(lines)


def get_processed_markdown():
    """Return markdown table of processed reciters."""
    processed = fetch_processed_reciters()
    if not processed:
        return "*No data available.*"
    lines = ["| Reciter | Source | Min Silence |",
             "|---------|--------|-------------|"]
    for r in processed:
        lines.append(
            f"| {r['name']} | {r.get('audio_source', '?')} "
            f"| {r.get('min_silence_ms', '?')}ms |"
        )
    return "\n".join(lines)


def handle_submit(reciter_json, request_type, riwayah, min_silence, name, email, notes):
    """Handle form submission from Gradio UI."""
    if not reciter_json:
        return "Error: Please select a reciter."

    try:
        info = json.loads(reciter_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: Invalid reciter selection."

    return submit_request(
        reciter_slug=info["slug"],
        reciter_name=info["name"],
        audio_source=info["source"],
        request_type=request_type,
        riwayah=riwayah,
        min_silence_ms=min_silence,
        requester_name=name,
        requester_email=email,
        notes=notes,
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
        return "*Guide not available — check back after the next deployment.*"


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
        "alignment pipeline. Track the status of all requests below."
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
                    reciter_dd = gr.Dropdown(
                        choices=get_reciter_choices(),
                        label="Reciter",
                        info="Select a reciter to request segmentation for. "
                             "Already-processed and pending reciters are excluded.",
                        filterable=True,
                    )
                    riwayah_dd = gr.Dropdown(
                        choices=RIWAYAT,
                        value="Hafs an Asim",
                        label="Riwayah",
                        info="Quranic reading tradition. Most existing reciters "
                             "use Hafs an Asim — verify by listening.",
                    )
                    min_silence = gr.Number(
                        value=500, label="Min Silence (ms)",
                        info="Minimum silence duration to split segments",
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
                        value=get_processed_markdown(),
                    )

            request_type_dd.change(
                fn=update_reciter_choices,
                inputs=[request_type_dd],
                outputs=[reciter_dd],
            )

            submit_btn.click(
                fn=handle_submit,
                inputs=[reciter_dd, request_type_dd, riwayah_dd,
                        min_silence, req_name, req_email, req_notes],
                outputs=result_box,
            )

        # ── Tab 2: Dashboard ──────────────────────────────────────────
        with gr.Tab("Dashboard"):
            refresh_btn = gr.Button("Refresh", variant="secondary")

            gr.Markdown("### Request Status")
            gr.Markdown(
                "All reciter segmentation requests and their current pipeline status."
            )
            requests_table = gr.Markdown(value=get_requests_markdown())

            gr.Markdown("### Completed Reciters")
            gr.Markdown(
                "Reciters that have been fully processed with their VAD parameters."
            )
            processed_table = gr.Markdown(value=get_processed_markdown())

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


# ---------------------------------------------------------------------------
# FastAPI app with custom API endpoints + Gradio mount
# ---------------------------------------------------------------------------
api = FastAPI()
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.post("/api/request")
async def api_request(request: Request):
    """API endpoint for Inspector form submissions."""
    req = await request.json()
    result = submit_request(
        reciter_slug=req.get("reciter_slug", ""),
        reciter_name=req.get("reciter_name", ""),
        audio_source=req.get("audio_source", ""),
        request_type=req.get("request_type", "New reciter"),
        riwayah=req.get("riwayah", "Hafs an Asim"),
        min_silence_ms=req.get("min_silence_ms", 500),
        requester_name=req.get("requester_name", ""),
        requester_email=req.get("requester_email", ""),
        notes=req.get("notes", ""),
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


@api.get("/api/reciters")
async def api_reciters():
    """List available (unprocessed) reciters."""
    return {"reciters": fetch_available_reciters()}


@api.get("/api/processed")
async def api_processed():
    """List processed reciters with VAD parameters."""
    return {"reciters": fetch_processed_reciters()}


@api.get("/api/requests")
async def api_requests():
    """List all request issues."""
    return {"requests": fetch_request_issues()}


@api.get("/api/guide")
async def api_guide():
    """Fetch the requesting-a-reciter guide markdown."""
    return {"markdown": fetch_guide()}


# Mount Gradio app onto FastAPI
app = gr.mount_gradio_app(api, demo, path="/")


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
