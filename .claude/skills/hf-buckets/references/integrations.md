# Library Integrations

Any fsspec-aware library reads/writes buckets via `hf://buckets/...` URIs once `huggingface_hub` is installed.

## pandas

```python
import pandas as pd
df = pd.read_parquet("hf://buckets/user/b/data.parquet")
df.to_parquet("hf://buckets/user/b/output.parquet")
```

`read_csv`/`to_csv`, `read_json`/`to_json` work identically.

## Polars

```python
import polars as pl
pl.read_parquet("hf://buckets/user/b/data.parquet")     # eager
pl.scan_parquet("hf://buckets/user/b/*.parquet")        # lazy
```

Globbing pulls multiple files into one DataFrame.

## Dask

```python
import dask.dataframe as dd
df = dd.read_parquet("hf://buckets/user/b/data.parquet")
```

## PyArrow

```python
import pyarrow.parquet as pq
table = pq.read_table("hf://buckets/user/b/data.parquet")
```

## DuckDB — explicit setup

DuckDB doesn't natively recognise `hf://buckets/` yet. Register `HfFileSystem` first.

```python
import duckdb
from huggingface_hub import HfFileSystem
duckdb.register_filesystem(HfFileSystem())
duckdb.sql("SELECT * FROM 'hf://buckets/user/b/data.parquet' LIMIT 10")
```

Native `hf://buckets/` support is on the DuckDB roadmap.

## PySpark

Install `pyspark_huggingface`:

```python
df = (spark.read.format("huggingface")
        .option("data_files", '["data.parquet"]')
        .load("buckets/user/b"))
```

## 🤗 Datasets

```python
from datasets import load_dataset
ds = load_dataset("buckets/user/b", data_files=["data.parquet"])
```

Note the path style omits `hf://` here — `datasets` resolves `buckets/<owner>/<name>` directly.

## Zarr (array store)

```python
import zarr
with zarr.open_group("hf://buckets/user/b/array-store", mode="w") as root:
    arr = root.create_group("emb").zeros("run_0", shape=(50000, 1000), dtype="f4")
    arr[:] = embeddings
```

## hffs — direct fsspec

```python
from huggingface_hub import hffs

hffs.ls("buckets/user/b")
with hffs.open("buckets/user/b/notes.md", "w") as f:
    f.write("...")
hffs.cp("buckets/user/b/a.txt", "buckets/user/b/b.txt")
hffs.glob("buckets/user/b/**/*.parquet")
```

## OpenDAL — non-Python

OpenDAL provides equivalent fsspec-style access for Rust, Java, Go, JavaScript, Node, and more. Use when the workload isn't Python.

## High-frequency append (streaming ingestion)

```python
from huggingface_hub import hffs
import json

with hffs.open("buckets/user/b/stream.jsonl", "w") as f:
    for item in stream:
        f.write(json.dumps(item) + "\n")
        f.flush()        # uploads buffered chunk; default blocksize 5 MiB
```

True append mode (`"a"`) is not yet supported — `flush()` is the workaround.

## Coming soon

Native `hf://buckets/` URL support announced for: Polars, DuckDB, Daft, WebDataset.
