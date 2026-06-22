# Access Patterns

Four ways to reach bucket data. Pick by use case.

| Method | Best for | Setup |
|--------|----------|-------|
| `hf-mount` (NFS/FUSE) | Any local tool — pandas/DuckDB/vLLM/training scripts/shell. Lazy byte-level fetch. | `brew install hf-mount` |
| Volume mount in Jobs/Spaces | Same idea, platform-managed. No local install. | `-v hf://buckets/...:/path` (see `jobs-and-spaces.md`) |
| `hf://buckets/` fsspec URIs | Python data libs (pandas, Dask, Polars, DuckDB, PyArrow, Datasets, Zarr) | `pip install huggingface_hub` |
| `hf buckets sync` / `cp` | Bulk transfers, backups, CI artifact upload | CLI |

S3 API: **not supported yet** (roadmap).

---

## hf-mount — local filesystem

Mounts a bucket as a directory via NFS (recommended) or FUSE. Bytes fetched lazily on read.

```bash
brew install hf-mount
hf-mount start bucket user/my-bucket /mnt/data
# any tool now sees /mnt/data as a regular directory
```

Buckets mount **read-write**; repos mount read-only. Backend options, caching, and write modes: see the `hf-mount` GitHub repo.

---

## fsspec — `HfFileSystem`

`huggingface_hub` ships a pre-instantiated `hffs` (`HfFileSystem`) that's fsspec-compatible.

```python
from huggingface_hub import hffs

hffs.ls("buckets/user/b/data", detail=False)
hffs.glob("buckets/user/b/**/*.parquet")
with hffs.open("buckets/user/b/hello.txt", "w") as f:
    f.write("hi")                                  # default mode is 'rb' — set 'w'/'r' for text
hffs.cp("buckets/user/b/a.txt", "buckets/user/b/b.txt")
hffs.rm("buckets/user/b/b.txt")
hffs.read_text("buckets/user/b/notes.md")          # `revision=` not allowed on buckets
```

Auth (if not logged in): `HfFileSystem(token=token)`.

**Append modes (`a`/`ab`) are not yet supported.** Workaround: open `"w"`, write incrementally, and call `flush()` to upload buffered chunks. Default fsspec blocksize is 5 MiB — every `flush()` after that triggers an upload.

```python
# Quasi-real-time append via flush
import json
with hffs.open("buckets/user/b/stream.jsonl", "w") as f:
    for item in stream:
        f.write(json.dumps(item) + "\n")
        f.flush()
```

Path scheme reminder:

```
hf://[<repo_type_prefix>]<repo_id>[@<revision>]/<path>
hf://buckets/<owner>/<name>/<path>           # buckets — no revision allowed
hf://datasets/<owner>/<name>/<path>          # datasets
hf://spaces/<owner>/<name>/<path>            # Spaces
hf://<owner>/<name>/<path>                   # models (no prefix)
```

---

## Performance note

`HfFileSystem` adds an fsspec compatibility layer that has measurable overhead. For bulk transfers, prefer `batch_bucket_files` / `download_bucket_files` / `sync_bucket` directly — they bypass fsspec.

Use the fsspec layer when:
- You need a library that only speaks fsspec (pandas, Polars, DuckDB, etc.)
- You're doing one-off interactive reads/writes

Use the direct APIs when:
- Moving many files at once
- Throughput matters
- You want resumability and dedup-aware transfer
