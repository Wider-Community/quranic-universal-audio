# Buckets — REST API

Direct HTTP endpoints under the `Buckets` tag in the Hub OpenAPI spec. Use these when writing a custom client (any language) instead of going through `huggingface_hub`.

**Spec source:** `https://huggingface.co/.well-known/openapi.md` — single canonical markdown file. The `huggingface/openapi` Space (`#tag/buckets`) just renders it. Authenticate any of these endpoints with the standard Hub bearer token: `Authorization: Bearer <hf_token>`.

## Endpoint table

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/buckets/{ns}/{repo}` | Create bucket |
| `DELETE` | `/api/buckets/{ns}/{repo}` | Delete bucket |
| `GET` | `/api/buckets/{ns}/{repo}` | Bucket details |
| `GET` | `/api/buckets/{ns}` | List namespace buckets (`?search=...`) |
| `PUT` | `/api/buckets/{ns}/{repo}/settings` | Update `private` + `cdnRegions` |
| `POST` | `/api/buckets/{ns}/{repo}/batch` | NDJSON file ops |
| `GET` | `/api/buckets/{ns}/{repo}/tree/{path}` | List files (paginated) |
| `POST` | `/api/buckets/{ns}/{repo}/paths-info` | Bulk metadata for known paths |
| `GET` | `/buckets/{ns}/{repo}/resolve/{path}` | File fetch — 302 redirect or JSON metadata |
| `POST` | `/api/buckets/{ns}/{repo}/resource-group` | Attach to resource group |
| `GET` | `/api/buckets/{ns}/{repo}/resource-group` | Get resource group |
| `GET` | `/api/buckets/{ns}/{repo}/xet-write-token` | Short-lived Xet write creds |
| `GET` | `/api/buckets/{ns}/{repo}/xet-read-token` | Short-lived Xet read creds |

---

## Create — `POST /api/buckets/{ns}/{repo}`

```json
{
  "private": false,
  "resourceGroupId": "<24-char hex>",
  "region": "us" | "eu",
  "cdn": [{"provider": "gcp" | "aws", "region": "us" | "eu"}]
}
```

- `region` sets where the bucket is hosted — **permanent**, no migration after creation.
- `cdn[]` pre-warms edge caches for compute located near those provider/region pairs.
- `200`: created. `409`: already exists (URL still returned).

## Update settings — `PUT /api/buckets/{ns}/{repo}/settings`

```json
{
  "private": true,
  "cdnRegions": [{"provider": "aws", "region": "eu"}]   // required
}
```

`cdnRegions` is required even if you only want to flip `private` — pass the existing list to keep them.

---

## Batch file ops — `POST /api/buckets/{ns}/{repo}/batch`

NDJSON body (one JSON object per line). **All `addFile`/`copyFile` lines must precede all `deleteFile` lines** — the server rejects out-of-order payloads.

```ndjson
{"type":"addFile","path":"models/m.bin","xetHash":"<hash>","mtime":1715000000,"contentType":"application/octet-stream"}
{"type":"copyFile","path":"models/c.json","xetHash":"<hash>","sourceRepoType":"model","sourceRepoId":"user/repo"}
{"type":"deleteFile","path":"old.bin"}
```

`sourceRepoType` ∈ `bucket | model | dataset | space`. Use `addFile` only after the file's bytes are already uploaded to Xet (CAS); the API just registers the file in the bucket's manifest by hash. `copyFile` registers an existing Xet hash from another repo/bucket — fully server-side, no byte transfer.

- `200`: success. `422`: validation failure (out-of-order ops, unknown hash, etc.).

This is the wire format that `huggingface_hub.batch_bucket_files()` produces.

---

## List files — `GET /api/buckets/{ns}/{repo}/tree/{path}`

Pagination is cursor-based:

| Query | Purpose |
|-------|---------|
| `limit` | Page size |
| `cursor` | Opaque pagination token (returned via `Link` header / response) |
| `recursive` | When `false`, returns collapsed directory entries instead of full descent |

**Caveat:** `recursive=false` does **not** have strong consistency — entries can be slightly stale or duplicated near pagination boundaries. Recursive listing is consistent.

## Bulk metadata — `POST /api/buckets/{ns}/{repo}/paths-info`

```json
{ "paths": ["a.txt", "models/m.safetensors"] }   // max 2000 paths per call
```

Or single string. Missing paths are silently omitted from the response — there's no per-path error. Chunk above 2000 client-side.

---

## File resolve — `GET /buckets/{ns}/{repo}/resolve/{path}`

Note this is **not** under `/api/`. Returns one of two things based on `Accept`:

| Accept header | Response |
|---------------|----------|
| `application/vnd.xet-fileinfo+json` | `200` JSON with size, hash, Xet bridge links |
| anything else (default) | `302` redirect to the Xet bridge for byte download |

Query params: `?download=true` (force `Content-Disposition: attachment`), `?noContentDisposition=true` (suppress it). Useful for tooling that wants metadata without fetching bytes — set the Accept header and read the JSON directly.

`400`: missing path. `404`: bucket or file missing.

---

## Xet token exchange

`GET /api/buckets/{ns}/{repo}/xet-{read,write}-token`

Hub bearer token in → short-lived Xet token out. The Xet token is **scoped to the single bucket and scope** (read or write); a write token supersedes read. To upload to multiple buckets, mint a token per bucket. Used internally by every SDK upload/download path; you only need to call this directly when implementing a CAS client from scratch.

Cross-reference: `https://huggingface.co/docs/xet/auth` (token request lifecycle, error model) and `https://huggingface.co/docs/xet/api` (the actual CAS endpoints — `POST /xorb/*`, `POST /shard`, reconstruction GETs — that consume the Xet token).

Token errors are standard:
- `401` — Hub token invalid/missing
- `403` — Hub token lacks permission for this bucket / asked for write but only got read
- `404` — bucket doesn't exist

---

## Resource groups

`POST /api/buckets/{ns}/{repo}/resource-group` body:

```json
{ "resourceGroupId": "<24-char hex>" | null }
```

`null` removes the bucket from its resource group. Same model as repos — used by enterprise namespaces for permission scoping.

`GET /api/buckets/{ns}/{repo}/resource-group` returns the current group.

---

## Mapping to `huggingface_hub` Python calls

| HTTP endpoint | Python equivalent |
|---------------|-------------------|
| `POST /api/buckets/{ns}/{repo}` | `create_bucket()` |
| `DELETE /api/buckets/{ns}/{repo}` | `delete_bucket()` |
| `GET /api/buckets/{ns}/{repo}` | `bucket_info()` |
| `GET /api/buckets/{ns}` | `list_buckets()` |
| `POST /api/buckets/{ns}/{repo}/batch` | `batch_bucket_files()` |
| `GET /api/buckets/{ns}/{repo}/tree/{path}` | `list_bucket_tree()` |
| `POST /api/buckets/{ns}/{repo}/paths-info` | `get_bucket_paths_info()` |
| `GET /buckets/{ns}/{repo}/resolve/{path}` (Accept JSON) | `get_bucket_file_metadata()` |
| `GET /buckets/{ns}/{repo}/resolve/{path}` (302) | `download_bucket_files()` (after Xet exchange) |
| Xet token endpoints | called transparently by the SDK |
| `PUT /api/buckets/{ns}/{repo}/settings` | (no Python helper yet — call the HTTP endpoint directly) |
| Resource-group endpoints | (no Python helper yet — call the HTTP endpoint directly) |

When the SDK lacks a wrapper, hit the HTTP endpoint directly with `requests` + `HfApi().token` (or `HfFolder.get_token()`).
