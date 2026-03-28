#!/usr/bin/env python3
"""
Reciter request automation pipeline orchestrator.

Subcommands (segments):
  triage              — Fetch pending requests from Notion, cross-check, output triage table
  generate-pbs        — Derive VAD params and rewrite PBS job array for accepted requests
  set-status          — Update GitHub labels + Notion status for the current batch
  notify              — Send emails via Gmail SMTP for the current batch
  prepare-pr          — Edit RECITERS.md + README.md for segments PR

Subcommands (timestamps):
  detect-timestamps    — Find processed reciters needing timestamp extraction
  run-timestamps       — Run extract_timestamps.py in parallel for detected reciters
  complete-timestamps  — Create per-reciter PRs, auto-merge, wait for CI, set status, notify

Usage:
  python scripts/process_requests.py triage
  python scripts/process_requests.py generate-pbs
  python scripts/process_requests.py set-status <status>
  python scripts/process_requests.py notify <template>
  python scripts/process_requests.py prepare-pr
  python scripts/process_requests.py detect-timestamps
  python scripts/process_requests.py run-timestamps
  python scripts/process_requests.py complete-timestamps [--skip-ci]
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_helpers import (
    REPO_ROOT,
    REPO_OWNER,
    REPO_NAME,
    HF_DATASET_ID,
    TIMESTAMPS_STATE_FILE,
    notion_query_pending,
    notion_update_status,
    gh_list_request_issues,
    gh_swap_label,
    gh_ensure_labels,
    gh_invite_collaborator,
    gh_create_draft_pr,
    gh_comment_on_issue,
    notion_update_pr_url,
    send_email,
    slug_from_name,
    parse_processed_table,
    detect_reciters_needing_timestamps,
    find_timestamps_dir,
    resolve_riwayah,
    derive_vad_params,
    load_state,
    save_state,
    audio_manifest_exists,
)
_STYLE_DISPLAY_TO_SLUG = {
    "Murattal": "murattal", "Mujawwad": "mujawwad", "Muallim": "muallim",
    "Children Repeat": "children_repeat", "Taraweeh": "taraweeh", "Unknown": "unknown",
}


def _style_display_to_slug(s):
    return _STYLE_DISPLAY_TO_SLUG.get(s, s.lower() if s else "")


from email_templates import (
    email_receipt,
    email_rejected_non_hafs,
    email_rejected_duplicate,
    email_rejected_already_processed,
    email_segments_ready,
    email_timestamps_done,
)


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------
def cmd_triage(args):
    """Fetch pending requests and cross-check for validity."""
    print("=" * 60)
    print("PHASE 1: TRIAGE")
    print("=" * 60)

    # Ensure required labels exist
    gh_ensure_labels({
        "status:rejected": ("d73a4a", "Request rejected"),
        "status:awaiting-review": ("f9d71c", "Segments ready, awaiting community review"),
        "status:completed": ("0e8a16", "Fully processed with timestamps"),
    })

    # 1. Fetch pending from Notion
    print("\nFetching pending requests from Notion...")
    try:
        pending = notion_query_pending()
    except Exception as e:
        print(f"ERROR: Failed to query Notion: {e}")
        print("Falling back to GitHub issues with status:pending...")
        pending = _fallback_pending_from_github()

    if not pending:
        print("No pending requests found.")
        return

    print(f"Found {len(pending)} pending request(s).\n")

    # 2. Load cross-check data
    reciters_md = (REPO_ROOT / "data" / "RECITERS.md").read_text()
    processed = parse_processed_table(reciters_md)
    processed_slugs = {r["slug"] for r in processed}

    open_issues = gh_list_request_issues(state="open")
    open_by_slug = {}
    for iss in open_issues:
        if iss["slug"]:
            open_by_slug.setdefault(iss["slug"], []).append(iss)

    # 3. Triage each request
    triage_results = []
    for req in pending:
        result = _triage_one(req, processed_slugs, open_by_slug, processed)
        triage_results.append(result)

    # 4. Print triage table
    print("\n" + "-" * 60)
    print("TRIAGE RESULTS")
    print("-" * 60)
    for i, t in enumerate(triage_results):
        status_icon = "✓" if t["action"] == "accept" else "✗"
        print(f"\n  [{i+1}] {status_icon} {t['req']['reciter_name']}")
        print(f"      Slug: {t['req']['slug']}")
        print(f"      Source: {t['req']['audio_source']}")
        print(f"      Type: {t['req']['request_type']}")
        print(f"      Riwayah: {t['req']['riwayah']}")
        print(f"      Min Silence: {t['req'].get('min_silence', 'N/A')}ms")
        print(f"      Issue: #{t['req']['issue_number']}")
        print(f"      Action: {t['action'].upper()}")
        if t.get("reason"):
            print(f"      Reason: {t['reason']}")
        if t.get("context"):
            print(f"      Context: {t['context']}")
        for w in t.get("warnings", []):
            print(f"      [WARN] {w}")

    print("\n" + "-" * 60)
    print("Review the above and confirm actions.")
    print("Then run: python scripts/process_requests.py generate-pbs")
    print("-" * 60)

    # 5. Save state
    state = {
        "batch_id": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "job_id": None,
        "requests": [],
    }

    for t in triage_results:
        req = t["req"]
        entry = {
            "slug": req["slug"],
            "name": req["reciter_name"],
            "source": req["audio_source"],
            "request_type": req["request_type"],
            "riwayah": req["riwayah"],
            "style": req.get("style", "Unknown"),
            "country": req.get("country", "unknown"),
            "issue_number": req["issue_number"],
            "issue_url": req["issue_url"],
            "page_id": req.get("page_id", ""),
            "requester_email": req.get("email", ""),
            "requester_name": req.get("requester_name", ""),
            "github_username": req.get("github_username", ""),
            "action": t["action"],
            "reject_reason": t.get("reason", ""),
            "status": "pending",
        }

        # Get min_silence: prefer Notion field, fall back to issue body
        min_silence = req.get("min_silence")
        if not min_silence:
            for iss in open_by_slug.get(req["slug"], []):
                m = re.search(r"\*\*Suggested Min Silence:\*\*\s*(\d+)", iss.get("body", ""))
                if m:
                    min_silence = int(m.group(1))
                    break
        entry["min_silence"] = int(min_silence) if min_silence else 500

        state["requests"].append(entry)

    save_state(state)
    print(f"\nState saved to {state['batch_id']}")


def _triage_one(req, processed_slugs, open_by_slug, processed):
    """Triage a single request. Returns dict with action and reason."""
    slug = req["slug"]

    # Check 1: Already processed
    if slug in processed_slugs:
        return {
            "req": req,
            "action": "reject",
            "reason": "already-processed",
            "context": "Reciter is already in the Processed Reciters table",
        }

    # Check 2: Non-Hafs riwayah
    if req["riwayah"] and req["riwayah"] != "Hafs an Asim":
        return {
            "req": req,
            "action": "reject",
            "reason": "non-hafs",
            "context": f"Riwayah is {req['riwayah']}, only Hafs an Asim supported",
        }

    # Check 3: Duplicate open issue
    existing = open_by_slug.get(slug, [])
    other_issues = [
        iss for iss in existing
        if iss["number"] != req["issue_number"]
        and iss["status"] not in ("rejected",)
    ]
    if other_issues and req["request_type"] == "New reciter":
        iss = other_issues[0]
        return {
            "req": req,
            "action": "reject",
            "reason": "duplicate",
            "context": f"Existing issue #{iss['number']} (status: {iss['status']})",
        }

    # Check 4: Re-align of never-processed → treat as new
    if req["request_type"] == "Re-align" and slug not in processed_slugs:
        return {
            "req": req,
            "action": "accept",
            "reason": None,
            "context": "Re-align of unprocessed reciter — treating as new alignment",
        }

    # Check 5: Re-align of processed reciter → needs operator confirmation
    if req["request_type"] == "Re-align" and slug in processed_slugs:
        proc = next((p for p in processed if p["slug"] == slug), None)
        return {
            "req": req,
            "action": "confirm",
            "reason": "re-align",
            "context": f"Existing: {proc['name']} (validated={proc.get('validated', False)}). Operator must confirm.",
        }

    # Check 6: Audio manifest exists
    if not audio_manifest_exists(slug, req["audio_source"]):
        return {
            "req": req,
            "action": "reject",
            "reason": "no-manifest",
            "context": f"Audio manifest not found: data/audio/{req['audio_source']}/{slug}.json",
        }

    # Metadata comparison — warn-only, never blocks acceptance
    warnings = []
    try:
        manifest_path = REPO_ROOT / "data" / "audio" / req["audio_source"] / f"{slug}.json"
        with open(manifest_path) as f:
            manifest_meta = json.load(f).get("_meta", {})
        submitted_style = _style_display_to_slug(req.get("style", ""))
        manifest_style = manifest_meta.get("style", "unknown")
        if submitted_style and manifest_style and submitted_style != manifest_style:
            warnings.append(f"Style mismatch: submitted={submitted_style}, manifest={manifest_style}")
        submitted_country = req.get("country", "unknown")
        manifest_country = manifest_meta.get("country", "unknown")
        if submitted_country != "unknown" and manifest_country != "unknown" and submitted_country != manifest_country:
            warnings.append(f"Country mismatch: submitted={submitted_country}, manifest={manifest_country}")
    except Exception:
        pass

    # All checks pass
    return {"req": req, "action": "accept", "reason": None, "context": None, "warnings": warnings}


def _fallback_pending_from_github():
    """Fallback: build pending list from GitHub issues when Notion is unavailable."""
    issues = gh_list_request_issues(state="open")
    pending = []
    for iss in issues:
        if iss["status"] != "pending":
            continue
        body = iss.get("body", "")

        def extract(field):
            m = re.search(rf"\*\*{field}:\*\*\s*(.+)", body)
            return m.group(1).strip() if m else ""

        gh_user = extract("GitHub")
        if gh_user.startswith("@"):
            gh_user = gh_user[1:]

        pending.append({
            "page_id": "",
            "requester_name": "",
            "email": "",
            "reciter_name": extract("Reciter"),
            "slug": extract("Slug"),
            "audio_source": extract("Audio Source"),
            "request_type": extract("Request Type"),
            "riwayah": extract("Riwayah") or "Hafs an Asim",
            "style": extract("Style") or "Unknown",
            "country": extract("Country") or "unknown",
            "min_silence": extract("Suggested Min Silence").replace("ms", ""),
            "github_username": gh_user,
            "issue_number": iss["number"],
            "issue_url": iss["url"],
            "notes": extract("Notes"),
        })
    return pending


# ---------------------------------------------------------------------------
# generate-pbs
# ---------------------------------------------------------------------------
def cmd_generate_pbs(args):
    """Derive VAD params and rewrite PBS job array."""
    print("=" * 60)
    print("PHASE 2: GENERATE PBS")
    print("=" * 60)

    state = load_state()
    accepted = [r for r in state["requests"] if r["action"] == "accept"]

    if not accepted:
        print("No accepted requests to process.")
        return

    print(f"\nGenerating PBS for {len(accepted)} reciter(s):\n")
    print(f"  {'Reciter':<40} {'Silence':>8} {'Speech':>8} {'Pad':>6} {'Source'}")
    print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*6} {'-'*20}")

    pbs_entries = []
    for i, req in enumerate(accepted):
        silence, speech, pad = derive_vad_params(req["min_silence"], req["slug"])
        req["min_speech"] = speech
        req["pad"] = pad
        req["pbs_index"] = i + 1

        entry = f'    "{req["slug"]},{silence},{speech},{pad},,{req["source"]}"'
        pbs_entries.append(entry)
        print(f"  {req['name']:<40} {silence:>8} {speech:>8} {pad:>6} {req['source']}")

    # Rewrite PBS file
    pbs_path = REPO_ROOT / "jobs" / "extract_segments.pbs"
    if not pbs_path.exists():
        print(f"\nERROR: PBS file not found at {pbs_path}")
        return

    pbs_text = pbs_path.read_text()

    # Update array range
    pbs_text = re.sub(r"#PBS -J \d+-\d+", f"#PBS -J 1-{len(accepted)}", pbs_text)

    # Update RECITERS array
    array_content = "\n".join(pbs_entries)
    pbs_text = re.sub(
        r"RECITERS=\(\n.*?\n\)",
        f"RECITERS=(\n{array_content}\n)",
        pbs_text,
        flags=re.DOTALL,
    )

    pbs_path.write_text(pbs_text)
    save_state(state)

    print(f"\nPBS file updated: {pbs_path}")
    print(f"Array range: 1-{len(accepted)}")
    print("\nReview the PBS file, then submit:")
    print("  bash scripts/sync_mfa.sh")
    print('  ssh katana "cd /srv/scratch/speechdata/ahmed/mfa_segments_extract && qsub jobs/extract_segments.pbs"')


# ---------------------------------------------------------------------------
# set-status
# ---------------------------------------------------------------------------
NOTION_STATUS_MAP = {
    "pending": "Pending",
    "rejected": "Rejected",
    "awaiting-review": "Awaiting Review",
    "completed": "Completed",
}


def cmd_set_status(args):
    """Update GitHub labels and Notion status for the batch."""
    new_status = args.status
    print(f"Setting status to: {new_status}")

    state = load_state()
    if args.job_id:
        state["job_id"] = args.job_id
        save_state(state)

    # Determine which requests to update
    if new_status == "rejected":
        targets = [r for r in state["requests"] if r["action"] == "reject"]
    else:
        targets = [r for r in state["requests"] if r["action"] == "accept"]

    for req in targets:
        old_label = f"status:{req['status']}"
        new_label = f"status:{new_status}"

        # GitHub label
        try:
            gh_swap_label(req["issue_number"], old_label, new_label)
            print(f"  #{req['issue_number']} {req['name']}: {old_label} → {new_label}")
        except Exception as e:
            print(f"  #{req['issue_number']} GitHub label failed: {e}")

        # Notion status
        notion_name = NOTION_STATUS_MAP.get(new_status, new_status.title())
        if req.get("page_id"):
            try:
                notion_update_status(req["page_id"], notion_name)
            except Exception as e:
                print(f"  #{req['issue_number']} Notion update failed: {e}")

        req["status"] = new_status

    save_state(state)
    print(f"\nUpdated {len(targets)} request(s).")


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------
def cmd_notify(args):
    """Send email notifications for the current batch."""
    template = args.template
    print(f"Sending '{template}' emails...")

    state = load_state()

    if template == "rejected":
        targets = [r for r in state["requests"] if r["action"] == "reject"]
        for req in targets:
            if not req.get("requester_email"):
                print(f"  #{req['issue_number']} {req['name']}: No email, skipping")
                continue

            reason = req.get("reject_reason", "")
            if reason == "non-hafs":
                subj, html = email_rejected_non_hafs(
                    req["name"], req["requester_name"],
                    req.get("riwayah", "unknown"), req["issue_url"],
                )
            elif reason == "duplicate":
                subj, html = email_rejected_duplicate(
                    req["name"], req["requester_name"],
                    req["issue_url"], "pending", req["issue_url"],
                )
            elif reason == "already-processed":
                subj, html = email_rejected_already_processed(
                    req["name"], req["requester_name"], req["issue_url"],
                )
            else:
                continue

            send_email(req["requester_email"], subj, html)

    elif template == "receipt":
        targets = [r for r in state["requests"] if r["action"] == "accept"]
        for req in targets:
            if not req.get("requester_email"):
                print(f"  #{req['issue_number']} {req['name']}: No email, skipping")
                continue
            subj, html = email_receipt(
                req["name"], req["requester_name"], req["issue_url"],
            )
            send_email(req["requester_email"], subj, html)

    elif template == "segments_ready":
        targets = [r for r in state["requests"] if r["action"] == "accept"]
        for req in targets:
            if not req.get("requester_email"):
                continue
            subj, html = email_segments_ready(
                req["name"], req["requester_name"],
                req["issue_url"], req.get("pr_url", ""),
            )
            send_email(req["requester_email"], subj, html)

    elif template == "timestamps_done":
        targets = [r for r in state["requests"] if r["action"] == "accept"]
        for req in targets:
            if not req.get("requester_email"):
                continue
            subj, html = email_timestamps_done(
                req["name"], req["requester_name"], req["issue_url"],
            )
            send_email(req["requester_email"], subj, html)

    else:
        print(f"Unknown template: {template}")
        print("Available: rejected, receipt, segments_ready, timestamps_done")


# ---------------------------------------------------------------------------
# prepare-pr
# ---------------------------------------------------------------------------
def cmd_prepare_pr(args):
    """Create per-reciter draft PRs with segment data."""
    print("=" * 60)
    print("PHASE 5: PREPARE PR")
    print("=" * 60)

    state = load_state()
    accepted = [r for r in state["requests"] if r["action"] == "accept"]

    if not accepted:
        print("No accepted requests to include in PR.")
        return

    # Ensure working tree is clean before branch operations
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if status.stdout.strip():
        print("ERROR: Working tree is not clean. Commit or stash changes first.")
        print(status.stdout)
        return

    print(f"\nCreating draft PRs for {len(accepted)} reciter(s)...\n")

    for req in accepted:
        slug = req["slug"]
        branch_slug = slug.replace("_", "-")
        branch = f"feat/add-segments-{branch_slug}"
        seg_dir = REPO_ROOT / "data" / "recitation_segments" / slug

        print(f"  {req['name']} → {branch}")

        # Check if branch already exists locally or remotely
        local_exists = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        ).returncode == 0
        remote_exists = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        ).returncode == 0

        if local_exists or remote_exists:
            print(f"    Branch {branch} already exists, skipping")
            continue

        # Check segment data exists
        if not seg_dir.is_dir():
            print(f"    ERROR: Segment dir not found: {seg_dir}")
            continue

        try:
            # Create branch from main
            subprocess.run(
                ["git", "checkout", "-b", branch, "main"],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )

            # Stage segment data only (RECITERS.md/README.md updated by CI post-merge)
            subprocess.run(
                ["git", "add", f"data/recitation_segments/{slug}/"],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )

            # Commit
            commit_msg = f"feat: add segments for {req['name']}\n\nRef #{req['issue_number']}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )

            # Push
            subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )

            # Create draft PR
            pr_title = f"feat: add segments for {req['name']}"
            pr_body = (
                f"## Summary\n"
                f"Segments for **{req['name']}** extracted via the alignment pipeline.\n\n"
                f"Ref #{req['issue_number']}\n\n"
                f"## Review\n"
                f"- [ ] Checkout this branch and run the Inspector\n"
                f"- [ ] Fix any validation issues\n"
                f"- [ ] Mark as ready for review when satisfied\n"
            )
            pr_url = gh_create_draft_pr(branch, pr_title, pr_body)
            print(f"    PR created: {pr_url}")
            req["pr_url"] = pr_url

            # Comment on the issue linking to the PR
            try:
                gh_comment_on_issue(
                    req["issue_number"],
                    f"Draft PR created: {pr_url}\n\n"
                    f"Checkout the branch and run the Inspector to review segments.",
                )
            except Exception as e:
                print(f"    Warning: failed to comment on issue: {e}")

            # Update Notion with PR URL
            if req.get("page_id"):
                try:
                    notion_update_pr_url(req["page_id"], pr_url)
                except Exception as e:
                    print(f"    Warning: failed to update Notion PR URL: {e}")

            # Invite collaborator if GitHub username provided
            if req.get("github_username"):
                gh_invite_collaborator(req["github_username"])

        except subprocess.CalledProcessError as e:
            print(f"    ERROR: {e.cmd[0]} failed: {e.stderr.strip()}")
            req["pr_url"] = ""
        except Exception as e:
            print(f"    ERROR: {e}")
            req["pr_url"] = ""
        finally:
            # Always return to main
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
            )

    save_state(state)
    print(f"\nDone. State saved with PR URLs.")


# ---------------------------------------------------------------------------
# detect-timestamps
# ---------------------------------------------------------------------------
def cmd_detect_timestamps(args):
    """Find processed reciters that need timestamp extraction."""
    print("=" * 60)
    print("DETECT RECITERS NEEDING TIMESTAMPS")
    print("=" * 60)

    candidates = detect_reciters_needing_timestamps()

    if not candidates:
        print("\nNo reciters need timestamp extraction.")
        return

    print(f"\nFound {len(candidates)} reciter(s) needing timestamps:\n")
    print(f"  {'Reciter':<40} {'Audio Source':<25} {'Seg Dir'}")
    print(f"  {'-'*40} {'-'*25} {'-'*40}")
    for c in candidates:
        print(f"  {c['name']:<40} {c['audio_source']:<25} {c['seg_dir']}")

    # Try to link to GitHub issues for email/status updates
    open_issues = gh_list_request_issues(state="open")
    closed_issues = gh_list_request_issues(state="closed")
    all_issues = open_issues + closed_issues
    issue_by_slug = {}
    for iss in all_issues:
        if iss["slug"] and iss["slug"] not in issue_by_slug:
            issue_by_slug[iss["slug"]] = iss

    # Also try Notion for requester info
    try:
        from request_helpers import NOTION_DATABASE_ID
        import httpx
        from request_helpers import _notion_headers, _notion_rich_text, _notion_title, _notion_email, _notion_url
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        r = httpx.post(url, headers=_notion_headers(), json={}, timeout=30)
        notion_pages = {
            _notion_rich_text(p["properties"].get("Slug", {})): p
            for p in r.json().get("results", [])
        }
    except Exception:
        notion_pages = {}

    # Save state
    state = {
        "batch_id": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "reciters": [],
    }
    for c in candidates:
        iss = issue_by_slug.get(c["slug"], {})
        notion_page = notion_pages.get(c["slug"], {})
        notion_props = notion_page.get("properties", {})

        state["reciters"].append({
            "slug": c["slug"],
            "name": c["name"],
            "audio_source": c["audio_source"],
            "seg_dir": c["seg_dir"],
            "issue_number": iss.get("number", 0),
            "issue_url": iss.get("url", ""),
            "page_id": notion_page.get("id", ""),
            "requester_email": _notion_email(notion_props.get("Email", {})) if notion_props else "",
            "requester_name": _notion_title(notion_props.get("Requester Name", {})) if notion_props else "",
        })

    save_state(state, TIMESTAMPS_STATE_FILE)
    print(f"\nState saved. Run: python scripts/process_requests.py run-timestamps")


# ---------------------------------------------------------------------------
# run-timestamps
# ---------------------------------------------------------------------------
def cmd_run_timestamps(args):
    """Run extract_timestamps.py in parallel for all detected reciters."""
    print("=" * 60)
    print("RUN TIMESTAMP EXTRACTION (PARALLEL)")
    print("=" * 60)

    state = load_state(TIMESTAMPS_STATE_FILE)
    reciters = state.get("reciters", [])

    if not reciters:
        print("No reciters in state. Run detect-timestamps first.")
        return

    print(f"\nLaunching {len(reciters)} parallel extraction(s)...\n")

    # Build commands
    extract_script = REPO_ROOT / "extract_timestamps.py"
    processes = {}
    for rec in reciters:
        cmd = [
            sys.executable, str(extract_script),
            "--input", rec["seg_dir"],
            "--resume",
        ]
        print(f"  Starting: {rec['name']}")
        log_path = REPO_ROOT / "data" / "recitation_segments" / rec["slug"] / "timestamps.log"
        log_file = open(log_path, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )
        processes[rec["slug"]] = {
            "proc": proc,
            "log_file": log_file,
            "log_path": log_path,
            "name": rec["name"],
        }

    # Wait for all to complete
    print(f"\nWaiting for {len(processes)} process(es)...")
    results = {}
    for slug, info in processes.items():
        rc = info["proc"].wait()
        info["log_file"].close()
        results[slug] = rc
        status = "OK" if rc == 0 else f"FAILED (exit {rc})"
        print(f"  {info['name']}: {status}")
        if rc != 0:
            print(f"    Log: {info['log_path']}")

    failed = [s for s, rc in results.items() if rc != 0]
    succeeded = [s for s, rc in results.items() if rc == 0]

    print(f"\nResults: {len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        print("Check logs and fix issues before proceeding.")

    if succeeded:
        print(f"\nNext: python scripts/process_requests.py complete-timestamps")


# ---------------------------------------------------------------------------
# complete-timestamps — Git / GitHub helpers
# ---------------------------------------------------------------------------
def _run_git(args, check=True):
    """Run a git command in REPO_ROOT."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, check=check,
    )


def _run_gh(args, check=True):
    """Run a gh CLI command in REPO_ROOT."""
    return subprocess.run(
        ["gh"] + args,
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, check=check,
    )


def _create_timestamps_pr(rec):
    """Create a branch, commit timestamp files, push, and open PR for one reciter.

    Returns dict with keys: success, pr_number, pr_url, reciter, merged, error.
    """
    slug = rec["slug"]
    branch = f"timestamps/{slug}"
    ts_dir = rec["ts_dir"]
    result = {
        "reciter": rec, "success": False, "pr_number": None,
        "pr_url": None, "merged": False, "error": None,
    }

    try:
        # Start from main
        _run_git(["checkout", "main"])

        # Clean up stale local/remote branches from previous failed runs
        _run_git(["branch", "-D", branch], check=False)
        _run_git(["push", "origin", "--delete", branch], check=False)

        _run_git(["checkout", "-b", branch])

        # Stage timestamp files (timestamps.json is sufficient for HF dataset)
        _run_git(["add", f"{ts_dir}/timestamps.json"])

        # Check something was actually staged
        staged = _run_git(["diff", "--cached", "--name-only"])
        staged_files = staged.stdout.strip().splitlines()

        if not staged_files:
            result["error"] = "No files staged (already committed or gitignored)"
            return result

        # Commit
        _run_git(["commit", "-m", f"feat: add timestamps for {rec['name']}"])

        # Push
        _run_git(["push", "-u", "origin", branch])

        # Create PR
        issue_ref = ""
        if rec.get("issue_number"):
            issue_ref = f"\n\nCloses #{rec['issue_number']}"
        pr_body = (
            f"Add word-level timestamps for **{rec['name']}** (`{slug}`)."
            f"{issue_ref}"
        )
        pr_result = _run_gh([
            "pr", "create",
            "--base", "main", "--head", branch,
            "--title", f"feat: add timestamps for {rec['name']}",
            "--body", pr_body,
        ])

        pr_url = pr_result.stdout.strip()
        pr_number = int(pr_url.rstrip("/").split("/")[-1])
        result.update(success=True, pr_number=pr_number, pr_url=pr_url)

    except subprocess.CalledProcessError as e:
        result["error"] = f"{' '.join(e.cmd)}: {e.stderr.strip()}"
    except Exception as e:
        result["error"] = str(e)
    finally:
        _run_git(["checkout", "main"], check=False)

    return result


def _merge_pr(pr):
    """Auto-merge a PR using --admin to bypass branch protection."""
    try:
        _run_gh([
            "pr", "merge", str(pr["pr_number"]),
            "--admin", "--merge", "--delete-branch",
        ])
        pr["merged"] = True
        print(f"  Merged PR #{pr['pr_number']}")
    except subprocess.CalledProcessError as e:
        pr["merged"] = False
        print(f"  Failed to merge PR #{pr['pr_number']}: {e.stderr.strip()}")


def _get_latest_run_id(workflow_file):
    """Get the databaseId of the most recent run for a workflow, or None."""
    try:
        r = _run_gh([
            "run", "list", "--workflow", workflow_file,
            "--branch", "main", "--limit", "1",
            "--json", "databaseId",
        ])
        runs = json.loads(r.stdout)
        return runs[0]["databaseId"] if runs else None
    except Exception:
        return None


def _wait_for_workflow(workflow_file, after_run_id=None, timeout=900,
                       poll_interval=15):
    """Poll until a workflow run newer than after_run_id completes on main.

    Returns the conclusion string ('success', 'failure', etc.) or None on
    timeout.
    """
    print(f"  Waiting for {workflow_file}...")
    time.sleep(5)  # let GitHub register the push event

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _run_gh([
                "run", "list", "--workflow", workflow_file,
                "--branch", "main", "--limit", "1",
                "--json", "status,conclusion,databaseId",
            ])
            runs = json.loads(r.stdout)
            if not runs:
                time.sleep(poll_interval)
                continue

            run = runs[0]
            run_id = run.get("databaseId")

            # Skip stale runs from before our merges
            if after_run_id and run_id == after_run_id:
                remaining = int(deadline - time.time())
                print(f"  {workflow_file}: waiting for new run... ({remaining}s remaining)")
                time.sleep(poll_interval)
                continue

            status = run.get("status", "")
            conclusion = run.get("conclusion", "")

            if status == "completed":
                print(f"  {workflow_file}: {conclusion}")
                return conclusion

            remaining = int(deadline - time.time())
            print(f"  {workflow_file}: {status}... ({remaining}s remaining)")
            time.sleep(poll_interval)

        except Exception as e:
            print(f"  Error polling {workflow_file}: {e}")
            time.sleep(poll_interval)

    print(f"  {workflow_file}: timed out after {timeout}s")
    return None


def _get_latest_release_tag():
    """Get the tag of the most recent GitHub release, or None."""
    try:
        r = _run_gh(["release", "list", "--limit", "1", "--json", "tagName"])
        releases = json.loads(r.stdout)
        return releases[0]["tagName"] if releases else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# complete-timestamps
# ---------------------------------------------------------------------------
def cmd_complete_timestamps(args):
    """Create per-reciter PRs, auto-merge, wait for CI, set status, notify."""
    print("=" * 60)
    print("COMPLETE TIMESTAMPS (AUTO PR + MERGE + NOTIFY)")
    print("=" * 60)

    state = load_state(TIMESTAMPS_STATE_FILE)
    reciters = state.get("reciters", [])
    if not reciters:
        print("No reciters in state. Run detect-timestamps first.")
        return

    # --- Phase 1: Validate timestamps exist ---
    completed = []
    for rec in reciters:
        ts_dir = find_timestamps_dir(rec["slug"])
        if ts_dir is None:
            print(f"  SKIP {rec['name']}: no timestamps found")
            continue
        rec["ts_dir"] = str(ts_dir)
        rec["riwayah"] = resolve_riwayah(rec["slug"])
        completed.append(rec)

    if not completed:
        print("\nNo completed timestamps found.")
        return

    print(f"\nFound {len(completed)} reciter(s) with timestamps.\n")

    # --- Phase 2: Snapshot pre-merge workflow state ---
    pre_merge_run_id = _get_latest_run_id("sync-dataset.yml")

    # Ensure we're on main and up-to-date
    _run_git(["checkout", "main"])
    _run_git(["pull", "origin", "main"])

    # --- Phase 3: Create PRs ---
    print("Creating PRs...")
    pr_results = []
    for rec in completed:
        result = _create_timestamps_pr(rec)
        pr_results.append(result)
        if result["success"]:
            print(f"  PR #{result['pr_number']}: {result['pr_url']}")
        else:
            print(f"  FAILED {rec['name']}: {result['error']}")

    successful = [r for r in pr_results if r["success"]]
    if not successful:
        print("\nAll PRs failed. Aborting.")
        return

    # --- Phase 4: Merge all PRs ---
    print(f"\nMerging {len(successful)} PR(s)...")
    for pr in successful:
        _merge_pr(pr)

    merged = [pr for pr in successful if pr["merged"]]
    print(f"\nMerged {len(merged)}/{len(successful)} PR(s).")

    if not merged:
        print("No PRs merged. Aborting.")
        return

    # Pull merged changes
    _run_git(["checkout", "main"])
    _run_git(["pull", "origin", "main"])

    # --- Phase 5: Wait for CI cascade ---
    release_tag = None
    if args.skip_ci:
        print("\n--skip-ci: skipping CI wait.")
        release_tag = _get_latest_release_tag()
    else:
        print("\nWaiting for CI cascade...")
        sync_conclusion = _wait_for_workflow(
            "sync-dataset.yml", after_run_id=pre_merge_run_id, timeout=900,
        )
        if sync_conclusion == "success":
            release_conclusion = _wait_for_workflow(
                "release.yml", timeout=600,
            )
            if release_conclusion == "success":
                release_tag = _get_latest_release_tag()
            else:
                print("  Release workflow did not succeed; skipping release URL.")
        else:
            print("  sync-dataset did not succeed; skipping release wait.")

    # --- Phase 6: Set status + notify ---
    release_url = (
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/{release_tag}"
        if release_tag else ""
    )

    print("\nSetting status and sending notifications...")
    for pr in merged:
        rec = pr["reciter"]
        slug = rec["slug"]
        riwayah = rec.get("riwayah", "hafs_an_asim")

        # HF viewer URL (timestamps.json is always sufficient for HF sync)
        dataset_url = (
            f"https://huggingface.co/datasets/{HF_DATASET_ID}"
            f"/viewer/{riwayah}/{slug}"
        )

        # GitHub label: status:awaiting-review -> status:completed
        if rec.get("issue_number"):
            try:
                gh_swap_label(
                    rec["issue_number"],
                    "status:awaiting-review", "status:completed",
                )
                print(f"  #{rec['issue_number']} label -> status:completed")
            except Exception as e:
                print(f"  #{rec['issue_number']} label failed: {e}")

        # Notion status
        if rec.get("page_id"):
            try:
                notion_update_status(rec["page_id"], "Completed")
            except Exception as e:
                print(f"  Notion update failed for {rec['name']}: {e}")

        # Email
        if rec.get("requester_email"):
            subj, html = email_timestamps_done(
                rec["name"], rec.get("requester_name", ""),
                rec.get("issue_url", ""),
                dataset_url=dataset_url,
                release_url=release_url,
            )
            send_email(rec["requester_email"], subj, html)
            print(f"  Emailed {rec['requester_email']}")
        else:
            print(f"  {rec['name']}: no email on file, skipping notification")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for pr in pr_results:
        rec = pr["reciter"]
        if pr.get("merged"):
            status = "MERGED"
        elif pr["success"]:
            status = "PR CREATED (not merged)"
        else:
            status = f"FAILED: {pr['error']}"
        print(f"  {rec['name']}: {status}")
    if release_url:
        print(f"\nRelease: {release_url}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Reciter request automation pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("triage", help="Fetch and triage pending requests")
    sub.add_parser("generate-pbs", help="Generate PBS job array")

    sp = sub.add_parser("set-status", help="Update status for current batch")
    sp.add_argument("status", choices=["pending", "rejected", "awaiting-review", "completed"])
    sp.add_argument("--job-id", help="PBS job ID to track")

    sp = sub.add_parser("notify", help="Send email notifications")
    sp.add_argument("template", choices=["rejected", "receipt", "segments_ready", "timestamps_done"])

    sub.add_parser("prepare-pr", help="Prepare PR staging instructions")

    sub.add_parser("detect-timestamps", help="Find reciters needing timestamps")
    sub.add_parser("run-timestamps", help="Run timestamp extraction in parallel")

    sp = sub.add_parser("complete-timestamps",
                        help="Auto PR + merge + CI wait + notify")
    sp.add_argument("--skip-ci", action="store_true",
                    help="Skip waiting for CI workflows")

    args = parser.parse_args()

    commands = {
        "triage": cmd_triage,
        "generate-pbs": cmd_generate_pbs,
        "set-status": cmd_set_status,
        "notify": cmd_notify,
        "prepare-pr": cmd_prepare_pr,
        "detect-timestamps": cmd_detect_timestamps,
        "run-timestamps": cmd_run_timestamps,
        "complete-timestamps": cmd_complete_timestamps,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
