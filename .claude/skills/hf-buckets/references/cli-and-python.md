# Buckets — CLI and Python

CLI prefix is `hf buckets <subcommand>`. Python lives in `huggingface_hub`. Most operations have parallel CLI and Python forms — pick by context.

## Create / inspect / delete / move

```bash
hf buckets create my-bucket                  # under your namespace
hf buckets create my-bucket --private
hf buckets create my-org/shared              # under an org
hf buckets create my-bucket --exist-ok       # don't error if exists

hf buckets info user/b                       # JSON metadata
hf buckets list                              # all your buckets (table)
hf buckets list -h                           # human-readable sizes
hf buckets list --search checkpoint
hf buckets list --quiet                      # one ID per line — pipe-friendly
hf buckets list --format json

hf buckets delete user/old --yes --missing-ok
hf buckets move user/old user/new            # rename
hf buckets move user/b my-org/b              # transfer to org
```

```python
from huggingface_hub import (
    create_bucket, bucket_info, list_buckets, delete_bucket, move_bucket,
)

url = create_bucket("my-bucket", private=False, exist_ok=True)
url.bucket_id   # 'username/my-bucket'
url.handle      # 'hf://buckets/username/my-bucket'

info = bucket_info("username/my-bucket")     # .id .private .size .total_files .created_at
for b in list_buckets(namespace="my-org", search="checkpoint"):
    print(b.id, b.size, b.total_files)
delete_bucket("username/old", missing_ok=True)
move_bucket(from_id="username/old", to_id="my-org/old")
```

---

## Listing files

`hf buckets list <id>` is **non-recursive by default**. Pass `-R` for recursive, `--tree` for ASCII tree, `-h` for human sizes, `-q` for one path per line.

```bash
hf buckets list user/b                       # top-level
hf buckets list user/b -R -h                 # recursive, sized
hf buckets list user/b --tree -R             # tree
hf buckets list user/b/sub                   # filter by prefix (works with full handle too)
```

```python
from huggingface_hub import list_bucket_tree
for item in list_bucket_tree("user/b", recursive=True, prefix="sub"):
    item.type      # 'file' | 'directory'
    item.path
    item.size
    item.xet_hash  # use to drive server-side copy by hash
```

---

## Upload — single file (`cp`)

Source first, destination second. Either side may be `hf://buckets/...` or a local path. `-` means stdin/stdout.

```bash
hf buckets cp ./model.safetensors hf://buckets/user/b/models/model.safetensors
hf buckets cp ./data.csv hf://buckets/user/b/logs/        # dir-style remote dest — keeps filename
echo hi | hf buckets cp - hf://buckets/user/b/hello.txt   # stdin
```

---

## Upload — batch / programmatic

```python
from huggingface_hub import batch_bucket_files

# Local paths
batch_bucket_files("user/b", add=[
    ("./model.safetensors", "models/model.safetensors"),
    ("./config.json",       "models/config.json"),
])

# Raw bytes
batch_bucket_files("user/b", add=[(b'{"k":"v"}', "config.json")])

# Combine add + delete in one call
batch_bucket_files("user/b",
    add=[("./new.bin", "model.bin")],
    delete=["old.bin"],
)

# Server-side copy by Xet hash (no data download/upload)
# Tuple: (source_repo_type, source_repo_id, xet_hash, destination_path)
batch_bucket_files("user/b", copy=[
    ("bucket", "user/src",  "<xet_hash>", "models/m.safetensors"),
    ("model",  "user/repo", "<xet_hash>", "models/c.safetensors"),
])
```

`batch_bucket_files` is **non-transactional** — partial success is possible if an error occurs mid-batch. Check return / re-run with `--dry-run` semantics if order matters.

---

## Download

```bash
hf buckets cp hf://buckets/user/b/config.json ./config.json
hf buckets cp hf://buckets/user/b/config.json ./data/         # dest is dir
hf buckets cp hf://buckets/user/b/config.json - | jq .        # stream to stdout
```

```python
from huggingface_hub import download_bucket_files, list_bucket_tree

download_bucket_files("user/b", files=[
    ("models/model.safetensors", "./local/model.safetensors"),
])

# Faster: pass BucketFile objects (skips per-file metadata fetch)
parquet = [i for i in list_bucket_tree("user/b", recursive=True)
           if i.type == "file" and i.path.endswith(".parquet")]
download_bucket_files("user/b", files=[(f, f"./out/{f.path}") for f in parquet])
```

---

## Delete files

Permanent — no recovery. `--dry-run` first when using `--recursive`.

```bash
hf buckets rm user/b/old-model.bin
hf buckets rm user/b/logs/ --recursive
hf buckets rm user/b --recursive --include "*.tmp"
hf buckets rm user/b/data/ --recursive --exclude "*.safetensors"
hf buckets rm user/b/checkpoints/ --recursive --dry-run
```

```python
batch_bucket_files("user/b", delete=["old.bin", "logs/debug.log"])
```

---

## Sync directories

`hf buckets sync` (alias `hf sync`) is the rsync-style command — only changed files transfer.

```bash
hf buckets sync ./data hf://buckets/user/b              # upload
hf buckets sync hf://buckets/user/b ./data              # download
hf buckets sync ./data hf://buckets/user/b --delete     # also remove extraneous on dest
hf buckets sync ./data hf://buckets/user/b --dry-run    # preview as JSONL on stdout
```

Filtering:

```bash
hf buckets sync ./data hf://buckets/user/b --include "*.safetensors" --exclude "*.tmp"
hf buckets sync ./data hf://buckets/user/b --filter-from filters.txt
```

`filters.txt` — first matching rule wins:

```text
# comment
- *.log
- *.tmp
+ *.safetensors
+ *.json
```

Comparison modes:

| Flag | Effect |
|------|--------|
| (default) | Compare size + mtime |
| `--ignore-times` | Compare size only |
| `--ignore-sizes` | Compare mtime only |
| `--existing` | Skip new files (only update existing) |
| `--ignore-existing` | Skip files that exist on dest (only create new) |

Plan-and-apply (review before executing):

```bash
hf buckets sync ./data hf://buckets/user/b --plan plan.jsonl   # writes plan, transfers nothing
# review/edit plan.jsonl
hf buckets sync --apply plan.jsonl
```

```python
from huggingface_hub import sync_bucket
sync_bucket("./data", "hf://buckets/user/b",
    delete=True, include=["*.parquet"], exclude=["*.tmp"],
    ignore_times=False, dry_run=False, verbose=True,
)
sync_bucket("./data", "hf://buckets/user/b", plan="plan.jsonl")
sync_bucket(apply="plan.jsonl")
plan = sync_bucket("./data", "hf://buckets/user/b", dry_run=True)
plan.summary()  # {'uploads': N, 'downloads': N, 'deletes': N, 'skips': N, 'total_size': N}
```

The plan file is JSONL — header line, then one line per operation (`upload`/`download`/`delete`/`skip` with path + reason). Hand-editable.

---

## Server-side copy across repos and buckets

Xet-tracked files transfer by content hash — instant for huge files. Non-Xet files (small text, READMEs) get auto-downloaded and re-uploaded.

```bash
hf buckets cp hf://buckets/src/b/logs/ hf://buckets/dst/b/logs/   # bucket → bucket
hf buckets cp hf://datasets/HuggingFaceFW/fineweb/data \
              hf://buckets/user/fineweb-data                       # repo → bucket
hf buckets cp hf://user/my-model/config.json \
              hf://buckets/user/b/models/config.json
```

```python
from huggingface_hub import copy_files
copy_files(
    "hf://datasets/user/ds/processed/",
    "hf://buckets/user/b/datasets/processed/",
)
```

**Bucket → repo is not supported yet** (roadmap).

---

## Advanced metadata

```python
from huggingface_hub import get_bucket_paths_info, get_bucket_file_metadata

# Batch metadata fetch for known paths — single request, no traversal
for info in get_bucket_paths_info("user/b", ["a.txt", "models/m.safetensors"]):
    info.path; info.size; info.xet_hash

# Single-file (size + xet hash)
get_bucket_file_metadata("user/b", "models/m.safetensors").size
```

Use `get_bucket_paths_info` instead of `list_bucket_tree` when you already know the exact paths.
