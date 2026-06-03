# Mounting Volumes in HF Jobs and Spaces

Same syntax. Same defaults. Buckets are read-write; repos are read-only.

## Volume URI

```
hf://[TYPE/]SOURCE:/MOUNT_PATH[:ro]
```

| TYPE | Source example | Default mode |
|------|----------------|--------------|
| (omitted) | `org/model` | model repo, read-only |
| `models/` | `models/openai/gpt-oss-120b` | read-only |
| `datasets/` | `datasets/stanfordnlp/imdb` | read-only |
| `spaces/` | `spaces/user/space` | read-only |
| `buckets/` | `buckets/user/my-bucket` | **read-write** |

Subpath supported: `hf://datasets/org/ds/train:/data`. Append `:ro` to force a bucket read-only.

---

## HF Jobs

```bash
# Bucket as writable output
hf jobs uv run -v hf://buckets/user/out:/training-outputs \
    sft.py --output-dir /training-outputs/v3

# Dataset (ro) + bucket (rw) together
hf jobs run -v hf://datasets/user/ds:/data -v hf://buckets/user/out:/output \
    python:3.12 python script.py

# DuckDB-on-dataset one-liner
hf jobs run -v hf://datasets/stanfordnlp/imdb:/dataset \
    duckdb/duckdb duckdb -c "SELECT * FROM '/dataset/**/*.parquet' LIMIT 5"
```

```python
from huggingface_hub import Volume, run_job, run_uv_job

run_job(
    image="python:3.12",
    command=["python", "train.py"],
    volumes=[
        Volume(type="dataset", source="user/ds",  mount_path="/data"),
        Volume(type="bucket",  source="user/out", mount_path="/output"),
        Volume(type="bucket",  source="user/in",  mount_path="/input", read_only=True),
        Volume(type="model",   source="user/m",   mount_path="/model"),
    ],
)

# Same volumes API works with UV scripts
run_uv_job(
    "train.py",
    script_args=["--output_dir", "/training-outputs/v3"],
    volumes=[Volume(type="bucket", source="user/my-bucket", mount_path="/training-outputs")],
    flavor="a10g-large",
)
```

`read_only=True` is the Python equivalent of the `:ro` CLI suffix. Requires `huggingface_hub >= 1.8.0`.

Job built-in env vars (always set inside the container): `JOB_ID`, `ACCELERATOR`, `CPU_CORES`, `MEMORY`. Forward your local HF token with `--secrets HF_TOKEN` (reads from env or the local `~/.cache/huggingface/token`).

---

## HF Spaces — persistence

Buckets replace the old ephemeral `/data` disk for Space persistence. They survive restarts. Mount RW by default.

```bash
# `set` REPLACES all volumes. To add one, list every volume you want.
hf spaces volumes set user/my-space \
    -v hf://buckets/user/my-bucket:/data \
    -v hf://datasets/user/ds:/datasets:ro \
    -v hf://models/user/m:/models
```

UI alternative: Space Settings → Storage Buckets → Attach. Programmatic: see `huggingface_hub`'s `manage-spaces` API.

After attaching, the bucket contents appear at the mount path inside the container at **runtime only** — not during the Docker build step. Use a bucket for runtime data; bake build-time assets into the image instead.

---

## Common Space-persistence pattern

1. `hf buckets create user/my-app-data`
2. `hf spaces volumes set user/my-space -v hf://buckets/user/my-app-data:/data`
3. Set Space Variables/Secrets that point the app at `/data` (e.g. `LABEL_STUDIO_BASE_DATA_DIR=/data`).
4. **Factory rebuild** the Space — required for the new variables to land.

---

## Read-only bucket mount

When a Space or Job should consume bucket data without being able to overwrite it:

```bash
hf jobs run -v hf://buckets/user/training-data:/data:ro python:3.12 ls /data
```

Useful for production inference Spaces reading frozen artifacts that other jobs write.
