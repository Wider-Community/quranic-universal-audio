"""
API helpers for the reciter request automation pipeline.

Provides functions for:
- Notion database querying and status updates
- GitHub issue label management
- Gmail SMTP email sending
- RECITERS.md parsing and editing
"""

import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_dotenv = Path(__file__).resolve().parent.parent / ".env"
if _dotenv.exists():
    for line in _dotenv.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_WATCHERS_DB_ID = os.environ.get("NOTION_WATCHERS_DB_ID", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
REPO_OWNER = "Wider-Community"
REPO_NAME = "quranic-universal-audio"
HF_DATASET_ID = "hetchyy/quranic-universal-ayahs"

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).resolve().parent / ".process_state.json"
TIMESTAMPS_STATE_FILE = Path(__file__).resolve().parent / ".timestamps_state.json"


# ---------------------------------------------------------------------------
# Notion API
# ---------------------------------------------------------------------------
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def notion_query_pending():
    """Query Notion database for requests with Status = Pending."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    body = {
        "filter": {
            "property": "Status",
            "select": {"equals": "Pending"},
        }
    }
    r = httpx.post(url, headers=_notion_headers(), json=body, timeout=30)
    r.raise_for_status()
    data = r.json()

    results = []
    for page in data.get("results", []):
        props = page["properties"]
        results.append({
            "page_id": page["id"],
            "requester_name": _notion_title(props.get("Requester Name", {})),
            "email": _notion_email(props.get("Email", {})),
            "reciter_name": _notion_rich_text(props.get("Reciter", {})),
            "slug": _notion_rich_text(props.get("Slug", {})),
            "audio_source": _notion_rich_text(props.get("Audio Source", {})),
            "riwayah": _notion_rich_text(props.get("Riwayah", {})),
            "style": _notion_rich_text(props.get("Style", {})),
            "country": _notion_rich_text(props.get("Country", {})),
            "issue_number": _notion_number(props.get("Issue Number", {})),
            "issue_url": _notion_url(props.get("GitHub Issue", {})),
            "min_silence": _notion_number(props.get("Min Silence", {})),
            "github_username": _notion_rich_text(props.get("GitHub Username", {})),
            "review_opt_in": props.get("Reviewer Opt-in", {}).get("checkbox", False),
            "notes": _notion_rich_text(props.get("Notes", {})),
        })
    return results


def notion_update_status(page_id, status):
    """Update the Status select property of a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {
        "properties": {
            "Status": {"select": {"name": status}},
        }
    }
    r = httpx.patch(url, headers=_notion_headers(), json=body, timeout=30)
    r.raise_for_status()


# Notion property extractors
def _notion_title(prop):
    try:
        return prop["title"][0]["text"]["content"]
    except (KeyError, IndexError):
        return ""


def _notion_rich_text(prop):
    try:
        return prop["rich_text"][0]["text"]["content"]
    except (KeyError, IndexError):
        return ""


def _notion_email(prop):
    return prop.get("email", "") or ""


def _notion_select(prop):
    try:
        return prop["select"]["name"]
    except (KeyError, TypeError):
        return ""


def _notion_number(prop):
    return prop.get("number") or 0


def _notion_url(prop):
    return prop.get("url", "") or ""


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def _gh_headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def gh_list_request_issues(state="open"):
    """Fetch request issues from GitHub."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    r = httpx.get(
        url,
        headers=_gh_headers(),
        params={"labels": "request-alignment", "state": state, "per_page": 100},
        timeout=30,
    )
    r.raise_for_status()
    issues = []
    for iss in r.json():
        labels = [l["name"] for l in iss.get("labels", [])]
        status = "pending"
        for l in labels:
            if l.startswith("status:"):
                status = l.split(":", 1)[1]

        body = iss.get("body", "")
        slug_match = re.search(r"\*\*Slug:\*\*\s*(\S+)", body)

        issues.append({
            "number": iss["number"],
            "title": iss["title"],
            "slug": slug_match.group(1) if slug_match else "",
            "status": status,
            "url": iss["html_url"],
            "labels": labels,
            "body": body,
        })
    return issues


def gh_swap_label(issue_number, old_label, new_label):
    """Remove old_label and add new_label on a GitHub issue."""
    base = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/labels"

    # Remove old label
    try:
        httpx.delete(
            f"{base}/{old_label}",
            headers=_gh_headers(),
            timeout=15,
        )
    except httpx.HTTPStatusError:
        pass  # Label might not exist

    # Add new label
    httpx.post(
        base,
        headers=_gh_headers(),
        json={"labels": [new_label]},
        timeout=15,
    )


def gh_invite_collaborator(username):
    """Invite a GitHub user as repo collaborator with write access."""
    if not username:
        return
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/collaborators/{username}"
    try:
        r = httpx.put(url, headers=_gh_headers(), json={"permission": "write"}, timeout=15)
        if r.status_code in (201, 204):
            print(f"  Invited @{username} as collaborator")
        elif r.status_code == 422:
            print(f"  @{username} is already a collaborator")
        else:
            print(f"  Failed to invite @{username}: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"  Failed to invite @{username}: {e}")


def gh_ensure_labels(labels):
    """Create missing GitHub labels. labels: dict of {name: (color, description)}."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/labels"
    existing = httpx.get(url, headers=_gh_headers(), params={"per_page": 100}, timeout=30)
    existing_names = {l["name"] for l in existing.json()}

    for name, (color, desc) in labels.items():
        if name not in existing_names:
            httpx.post(
                url,
                headers=_gh_headers(),
                json={"name": name, "color": color, "description": desc},
                timeout=15,
            )
            print(f"  Created label: {name}")


def gh_create_draft_pr(branch, title, body):
    """Create a draft pull request. Returns PR html_url."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls"
    r = httpx.post(
        url,
        headers=_gh_headers(),
        json={
            "title": title,
            "body": body,
            "head": branch,
            "base": "main",
            "draft": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["html_url"]


def gh_comment_on_issue(issue_number, body):
    """Post a comment on a GitHub issue."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    r = httpx.post(
        url,
        headers=_gh_headers(),
        json={"body": body},
        timeout=15,
    )
    r.raise_for_status()


def notion_update_pr_url(page_id, pr_url):
    """Update the Pull Request URL property of a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {
        "properties": {
            "Pull Request": {"url": pr_url},
        }
    }
    r = httpx.patch(url, headers=_notion_headers(), json=body, timeout=30)
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Notion Watchers helpers
# ---------------------------------------------------------------------------
def notion_get_watchers_for_targets(targets, target_type="reciter"):
    """Return {target: [{email, name}]} for watchers matching the given targets.

    Queries the NOTION_WATCHERS_DB_ID database for all entries of the given
    target_type and filters to the requested target set.
    """
    if not NOTION_API_KEY or not NOTION_WATCHERS_DB_ID:
        return {}
    url = f"https://api.notion.com/v1/databases/{NOTION_WATCHERS_DB_ID}/query"
    body = {
        "filter": {
            "property": "Watch Target Type",
            "select": {"equals": target_type},
        },
        "page_size": 100,
    }
    result = {}
    try:
        r = httpx.post(url, headers=_notion_headers(), json=body, timeout=30)
        r.raise_for_status()
        pages = r.json().get("results", [])
        target_set = set(targets)
        for p in pages:
            props = p["properties"]
            target_rt = props.get("Watch Target", {}).get("rich_text", [])
            target_val = target_rt[0]["plain_text"] if target_rt else ""
            if target_val not in target_set:
                continue
            email_val = props.get("Email", {}).get("email", "")
            if not email_val:
                continue
            name_rt = props.get("Watcher Name", {}).get("rich_text", [])
            name_val = name_rt[0]["plain_text"] if name_rt else ""
            result.setdefault(target_val, []).append({
                "email": email_val,
                "name": name_val,
            })
    except Exception as e:
        print(f"  Warning: Failed to query watchers: {e}")
    return result


# ---------------------------------------------------------------------------
# Gmail SMTP email
# ---------------------------------------------------------------------------
def send_email(to, subject, html):
    """Send an email via Gmail SMTP. Returns True on success."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print(f"  [SKIP] No GMAIL_ADDRESS/GMAIL_APP_PASSWORD — would send to {to}: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to, msg.as_string())
        print(f"  Email sent to {to}: {subject}")
        return True
    except Exception as e:
        print(f"  Email failed: {e}")
        return False


# ---------------------------------------------------------------------------
# RECITERS.md parsing and editing
# ---------------------------------------------------------------------------
def slug_from_name(name):
    """Convert display name to snake_case slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_processed_table(md_text):
    """Parse all Aligned Reciters tables from RECITERS.md.

    The new format has multiple tables grouped by qira'ah > riwayah.
    Each table: | Reciter | Style | Source | Granularity | Coverage | Segmented | Manually Validated | Timestamped |
    """
    processed = []
    in_aligned = False
    in_table = False
    for line in md_text.split("\n"):
        if "## Aligned Reciters" in line:
            in_aligned = True
            continue
        if in_aligned and line.startswith("## ") and "Aligned" not in line:
            break  # Hit next major section
        if not in_aligned:
            continue
        if "| Reciter" in line and "Segmented" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 8:
                processed.append({
                    "name": cols[0],
                    "slug": slug_from_name(cols[0]),
                    "style": cols[1],
                    "source": cols[2],
                    "granularity": cols[3],
                    "coverage": cols[4],
                    "segmented": cols[5].strip() in ("✓", "✓✓"),
                    "validated": cols[6].strip() in ("✓", "✓✓"),
                    "timestamped": cols[7].strip() in ("✓", "✓✓"),
                })
        elif in_table and not line.strip().startswith("|"):
            in_table = False
    return processed


def parse_available_tables(md_text):
    """Parse all Available Reciters tables. Returns {riwayah: [name, ...]}."""
    tables = {}
    in_available = False
    current_riwayah = None
    in_table = False

    for line in md_text.split("\n"):
        if "## Available Reciters" in line:
            in_available = True
            continue
        if in_available and line.startswith("## ") and "Available" not in line:
            break
        if not in_available:
            continue
        if line.startswith("#### "):
            current_riwayah = line.lstrip("# ").strip()
            tables.setdefault(current_riwayah, [])
            in_table = False
            continue
        if current_riwayah and line.startswith("|---"):
            in_table = True
            continue
        if current_riwayah and "| # |" in line:
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 2:
                tables[current_riwayah].append(cols[1])
        elif in_table and not line.strip().startswith("|") and line.strip():
            in_table = False

    return tables


def remove_from_available(md_text, reciter_name, source_path):
    """Remove a reciter from the Available table and re-number rows.

    Deprecated: RECITERS.md is now fully auto-generated by list_reciters.py --write.
    Kept for audit_reciters.py compatibility.
    """
    lines = md_text.split("\n")
    result = []
    current_category = None
    current_source = None
    in_target_table = False
    row_num = 0
    removed = False

    for line in lines:
        if line.startswith("### By Surah"):
            current_category = "by_surah"
        elif line.startswith("### By Ayah"):
            current_category = "by_ayah"

        m = re.match(r"^####\s+`([^`]+)`", line)
        if m and current_category:
            src = f"{current_category}/{m.group(1)}"
            in_target_table = src == source_path
            row_num = 0

        # Check if this is the row to remove
        if in_target_table and line.startswith("|") and not line.startswith("|---") and "| # |" not in line:
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 2:
                name = cols[1]
                if slug_from_name(name) == slug_from_name(reciter_name):
                    removed = True
                    continue  # Skip this row
                row_num += 1
                result.append(f"| {row_num} | {name} |")
                continue

        result.append(line)

    if not removed:
        print(f"  WARNING: Could not find '{reciter_name}' in {source_path}")

    return "\n".join(result)


def add_to_processed(md_text, reciter_name, coverage="114 surahs, 6236 ayahs"):
    """Add a reciter to the Processed Reciters table.

    Deprecated: RECITERS.md is now fully auto-generated by list_reciters.py --write.
    Kept for audit_reciters.py compatibility.
    """
    lines = md_text.split("\n")
    result = []
    inserted = False

    for i, line in enumerate(lines):
        result.append(line)
        # Insert after the last row of the processed table (before the --- separator)
        if not inserted and line.startswith("|") and "| Reciter" not in line and "|---" not in line:
            # Check if next line is not a table row (end of processed table)
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if not next_line.startswith("|"):
                new_row = f"| {reciter_name} | {coverage} | ✓ | ✗ | ✗ |"
                result.append(new_row)
                inserted = True

    return "\n".join(result)


def update_readme_processed_count(readme_text, new_processed_count):
    """Update the 'X fully processed' count in README.md paragraph.

    Deprecated: README badges are now updated by list_reciters.py --write.
    """
    return re.sub(
        r"(\d+) fully processed",
        f"{new_processed_count} fully processed",
        readme_text,
    )


def update_timestamped_status(md_text, reciter_name, level="✓✓"):
    """Update the Timestamped column for a processed reciter in RECITERS.md.

    Deprecated: RECITERS.md is now fully auto-generated by list_reciters.py --write.
    Kept for audit_reciters.py compatibility.

    level: "✓✓" (words + letters/phonemes) or "✓" (words only)
    """
    lines = md_text.split("\n")
    result = []
    target_slug = slug_from_name(reciter_name)

    for line in lines:
        if line.startswith("|") and "| Reciter" not in line and "|---" not in line:
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 5 and slug_from_name(cols[0]) == target_slug:
                cols[4] = level
                line = "| " + " | ".join(cols) + " |"
        result.append(line)

    return "\n".join(result)


def detect_reciters_needing_timestamps():
    """Find processed reciters with segments but no timestamps."""
    md = (REPO_ROOT / "data" / "RECITERS.md").read_text()
    processed = parse_processed_table(md)

    candidates = []
    for rec in processed:
        if rec["timestamped"]:
            continue
        slug = rec["slug"]
        # Check segments exist
        seg_dir = REPO_ROOT / "data" / "recitation_segments" / slug
        if not (seg_dir / "detailed.json").exists():
            continue
        # Check timestamps don't exist yet
        has_timestamps = False
        for audio_type in ("by_surah_audio", "by_ayah_audio"):
            ts_dir = REPO_ROOT / "data" / "timestamps" / audio_type / slug
            if (ts_dir / "timestamps.json").exists():
                has_timestamps = True
                break
        if has_timestamps:
            continue

        # Determine audio source from segments.json _meta
        audio_source = ""
        seg_file = seg_dir / "segments.json"
        if seg_file.exists():
            try:
                first_line = seg_file.read_text().split("\n", 1)[0]
                meta = json.loads(first_line).get("_meta", {})
                audio_source = meta.get("audio_source", "")
            except Exception:
                pass

        candidates.append({
            "slug": slug,
            "name": rec["name"],
            "audio_source": audio_source,
            "seg_dir": str(seg_dir),
        })

    return candidates


def find_timestamps_dir(slug):
    """Find the timestamps directory for a reciter (by_ayah_audio or by_surah_audio).

    Returns the Path to the directory containing timestamps.json, or None.
    """
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        ts_dir = REPO_ROOT / "data" / "timestamps" / audio_type / slug
        if (ts_dir / "timestamps.json").exists():
            return ts_dir
    return None


def resolve_riwayah(slug):
    """Resolve the riwayah for a reciter from its audio manifest _meta.

    Chain: segments.json _meta.audio_source -> audio manifest _meta.riwayah.
    Returns riwayah string (default: 'hafs_an_asim').
    """
    seg_file = REPO_ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if not seg_file.exists():
        return "hafs_an_asim"
    try:
        first_line = seg_file.read_text(encoding="utf-8").split("\n", 1)[0]
        audio_source = json.loads(first_line).get("_meta", {}).get("audio_source", "")
    except Exception:
        return "hafs_an_asim"
    if not audio_source:
        return "hafs_an_asim"
    manifest = REPO_ROOT / "data" / "audio" / audio_source / f"{slug}.json"
    if not manifest.exists():
        return "hafs_an_asim"
    try:
        first_line = manifest.read_text(encoding="utf-8").split("\n", 1)[0]
        return json.loads(first_line).get("_meta", {}).get("riwayah", "hafs_an_asim")
    except Exception:
        return "hafs_an_asim"


# ---------------------------------------------------------------------------
# VAD parameter derivation
# ---------------------------------------------------------------------------
def derive_vad_params(min_silence, slug=""):
    """Derive min_speech and pad from min_silence."""
    min_speech = min_silence
    pad = int(min_silence * 0.4)
    return min_silence, min_speech, pad


# ---------------------------------------------------------------------------
# Batch state management
# ---------------------------------------------------------------------------
def load_state(path=None):
    """Load the current batch state from disk."""
    p = path or STATE_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {"batch_id": None, "job_id": None, "requests": []}


def save_state(state, path=None):
    """Save the current batch state to disk."""
    p = path or STATE_FILE
    p.write_text(json.dumps(state, indent=2))


def audio_manifest_exists(slug, source):
    """Check if the audio manifest JSON file exists locally."""
    manifest = REPO_ROOT / "data" / "audio" / source / f"{slug}.json"
    return manifest.exists()
