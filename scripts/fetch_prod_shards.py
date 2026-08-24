"""Download all prod-bucket timestamp shards into inspector/dev_fixtures/ (local).

Read-only: pulls reciters/<slug>/timestamps/*.json.br from the PROD bucket into a
bucket-shaped local tree so the inspector can serve them via TS_DEV_FIXTURES
without ever hitting the bucket. Files are read-only local evidence; migration
commands write a separate staging directory.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "scripts/bucket")
import _bootstrap as bs  # noqa: E402

bs.load_hf_token()
from huggingface_hub import HfFileSystem  # noqa: E402

DEST = Path("inspector/dev_fixtures")
fs = HfFileSystem()
bucket = bs.BUCKETS["prod"]


def _read(path: str) -> bytes:
    for _attempt in range(6):
        try:
            payload = fs.read_bytes(path)
            return payload if isinstance(payload, bytes) else payload.encode()
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate limit" in str(e).lower():
                time.sleep(30)
                continue
            raise
    raise RuntimeError(f"rate-limit retries exhausted for {path}")


def fetch_reciter(slug: str) -> tuple[str, int]:
    tpath = bs.abs_path(bucket, f"reciters/{slug}/timestamps")
    try:
        files = [
            path
            for path in fs.ls(tpath, detail=False)
            if isinstance(path, str) and path.endswith(".json.br")
        ]
    except FileNotFoundError:
        return slug, 0
    outdir = DEST / "reciters" / slug / "timestamps"
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        (outdir / f.split("/")[-1]).write_bytes(_read(f))
        n += 1
    return slug, n


def main() -> None:
    base = bs.abs_path(bucket, "reciters")
    recs = sorted(
        path.split("/")[-1] for path in fs.ls(base, detail=False) if isinstance(path, str)
    )
    total = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for slug, n in ex.map(fetch_reciter, recs):
            total += n
            if n:
                print(f"  {slug}: {n}", flush=True)
    print(f"\nfetched {total} shards into {DEST}", flush=True)


if __name__ == "__main__":
    main()
