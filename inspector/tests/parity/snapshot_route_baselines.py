"""Capture MUST-1 route-shape baselines for each fixture.

Run once (or after a deliberate API change) to regenerate the frozen
``expected/<fixture>.routes.json`` files:

    cd inspector
    python -m tests.parity.snapshot_route_baselines

Each output file records the top-level field keys returned by every
relevant route for the fixture's reciter/chapter.  The MUST-1 invariant
is "no field removed", so tracking keys — not full response bodies — is
sufficient and avoids noisy diffs from timestamps and dynamic data.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "segments"
EXPECTED_DIR = FIXTURES_DIR / "expected"

# Mapping: fixture name → chapter number used for the /data/<reciter>/<chapter> probe.
# Uses the first chapter ref found in each fixture's entries.
FIXTURE_CHAPTERS: dict[str, int] = {
    "112-ikhlas": 112,
    "113-falaq": 113,
    "synthetic-structural": 1,
    "synthetic-classifier": 1,
}


def _keys(value: object) -> list[str]:
    """Return sorted top-level keys if value is a dict, else empty list."""
    if isinstance(value, dict):
        return sorted(value.keys())
    return []


def _capture_fixture(name: str, chapter: int) -> dict:
    """Spin up a fresh Flask test client against a tmp fixture dir and hit all routes."""
    inspector_dir = Path(__file__).resolve().parents[2]

    tmp = tempfile.mkdtemp()
    try:
        reciter_root = Path(tmp) / "recitation_segments"
        reciter_dir = reciter_root / "fixture_reciter"
        reciter_dir.mkdir(parents=True)
        shutil.copy(
            str(FIXTURES_DIR / f"{name}.detailed.json"),
            str(reciter_dir / "detailed.json"),
        )

        # Patch path constants before importing routes/services that capture them.
        os.environ["INSPECTOR_DATA_DIR"] = tmp

        # We need to import fresh or patch already-imported modules.
        # Use a subprocess so we get a fully clean Python state.
        script = f"""
import sys, json, os, shutil
from pathlib import Path
sys.path.insert(0, {str(inspector_dir)!r})

os.environ['INSPECTOR_DATA_DIR'] = {tmp!r}

from pathlib import Path as _P
_reciter_root = _P({str(reciter_root)!r})

import config as _cfg
_cfg.RECITATION_SEGMENTS_PATH = _reciter_root

for mod_name in ('routes.segments_data', 'routes.segments_edit',
                 'routes.segments_validation', 'services.data_loader',
                 'services.history_query', 'services.save', 'services.undo'):
    import importlib
    try:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, 'RECITATION_SEGMENTS_PATH'):
            mod.RECITATION_SEGMENTS_PATH = _reciter_root
    except ImportError:
        pass

from app import app
app.config['TESTING'] = True
client = app.test_client()

results = {{}}

r = client.get('/api/seg/validate/fixture_reciter')
results['validate'] = {{'status_code': r.status_code, 'field_keys_top_level': sorted((r.get_json() or {{}}).keys()) if r.status_code == 200 else []}}

r = client.get('/api/seg/data/fixture_reciter/{chapter}')
results['data'] = {{'status_code': r.status_code, 'field_keys_top_level': sorted((r.get_json() or {{}}).keys()) if r.status_code == 200 else []}}

r = client.get('/api/seg/all/fixture_reciter')
results['all'] = {{'status_code': r.status_code, 'field_keys_top_level': sorted((r.get_json() or {{}}).keys()) if r.status_code == 200 else []}}

r = client.get('/api/seg/edit-history/fixture_reciter')
body = r.get_json() if r.status_code == 200 else None
if isinstance(body, dict):
    h_keys = sorted(body.keys())
elif isinstance(body, list):
    h_keys = ['<list>']
else:
    h_keys = []
results['edit_history'] = {{'status_code': r.status_code, 'field_keys_top_level': h_keys}}

r = client.get('/api/seg/config')
results['config'] = {{'status_code': r.status_code, 'field_keys_top_level': sorted((r.get_json() or {{}}).keys()) if r.status_code == 200 else []}}

print(json.dumps(results))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(inspector_dir),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"subprocess failed for fixture {name!r}:\n{proc.stderr}"
            )
        return json.loads(proc.stdout.strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def regenerate(name: str, chapter: int) -> Path:
    """Capture route shapes for *name* and write ``expected/<name>.routes.json``."""
    results = _capture_fixture(name, chapter)
    sha = _git_sha()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    out = {
        "_meta": {
            "fixture": name,
            "captured_against_commit": sha,
            "captured_at_utc": now,
            "policy": (
                "MUST-1 baseline; response field set must remain a superset of "
                "this on every subsequent commit"
            ),
        },
        "validate": results["validate"],
        "data": results["data"],
        "all": results["all"],
        "edit_history": results["edit_history"],
        "config": results["config"],
    }
    out_path = EXPECTED_DIR / f"{name}.routes.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    fixtures = argv or list(FIXTURE_CHAPTERS.keys())
    for name in fixtures:
        chapter = FIXTURE_CHAPTERS.get(name, 1)
        path = regenerate(name, chapter)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
