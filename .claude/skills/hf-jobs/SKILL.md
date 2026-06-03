---
name: hf-jobs
description: Reference for running workloads on Hugging Face Jobs.
---

# Hugging Face Jobs

Cloud compute on HF infra. Pay-per-second. Pro/Team/Enterprise plan required.

Three surfaces — same model under each:

| Surface | Use when |
|---------|----------|
| `hf jobs ...` CLI | One-off submissions, quick scripts, shell pipelines, inspecting state |
| `huggingface_hub` Python (`run_job`, `run_uv_job`, `Volume`, `inspect_job`, `fetch_job_logs`, `create_scheduled_job`) | Programmatic submission, parallel fan-out, scripted orchestration |
| `hf_jobs(...)` MCP tool | Submitting via Claude in this session — `script` accepts inline Python directly, `$HF_TOKEN` is auto-substituted in `secrets` |

The plugin skill `huggingface-skills:hugging-face-jobs` has the long-form reference (token semantics across all three surfaces, sample patterns like vLLM batch generation, troubleshooting matrix). This project skill is the project-fit layer plus a compact CLI/Python cheat sheet — open it first, escalate to the plugin skill for general patterns.

## Reference index

| File | Open when working on |
|------|----------------------|
| `references/cli-and-python.md` | CLI and Python cheat sheet — `hf jobs run`, `hf jobs uv run`, ps/logs/inspect/stats/cancel, scheduled jobs, hardware flavors + costs, `--timeout` / `--namespace` / `--label` / `-e` / `-s` / `--env-file` / `--secrets-file`, volume mount syntax, `Volume` class, built-in env vars (`JOB_ID`, `ACCELERATOR`, `CPU_CORES`, `MEMORY`), webhook triggers |

## Always-true essentials

- **UV is the default surface.** `hf jobs uv run` (or `hf_jobs("uv", ...)`) takes a script (local path via CLI; **inline string or URL** via MCP — local paths fail in MCP because the container can't see them) with PEP 723 inline deps. Plain Docker (`hf jobs run <image> <cmd>`) is the escape hatch for non-Python or pre-built images (vLLM, DuckDB, pytorch/pytorch).
- **Default UV image:** `ghcr.io/astral-sh/uv:python3.12-bookworm`. Override with `--image` for ML-heavy frameworks.
- **Default timeout is 30 min.** Always pass `--timeout` for anything training-shaped. Format: `30m`, `1.5h`, `1d`, or seconds.
- **Default flavor is `cpu-basic`.** Pass `--flavor` for GPU/TPU. List + prices: `hf jobs hardware`.
- **Environment is ephemeral.** Anything not pushed to a Hub repo, written to a mounted bucket, or POSTed elsewhere dies with the container. For training, mount a bucket as the output dir.
- **Token forwarding:** CLI `--secrets HF_TOKEN` (reads local env / `~/.cache/huggingface/token`); MCP `secrets={"HF_TOKEN": "$HF_TOKEN"}` (auto-replaced); Python API `secrets={"HF_TOKEN": get_token()}` (the literal `"$HF_TOKEN"` will 401).
- **Volume mounts:** `-v hf://[TYPE/]SOURCE:/MOUNT_PATH[:ro]`. Models/datasets read-only always; buckets read-write by default. Requires `huggingface_hub >= 1.8.0` for the Python `Volume` class.
- **Namespace:** jobs land in your user namespace by default. `--namespace <org>` for organization billing/visibility.
- **Async by default.** Submission returns a `JobInfo` with `id` + `url`. Don't poll in a tight loop — `inspect_job` or `hf jobs ps --filter status=running` when the user asks.
- **Auth check:** `hf auth whoami` (or `hf_whoami()`). Plan gate: Jobs are paid-tier only, so 403 on submission usually means a free account, not bad code.

## Auth

`hf auth login` once locally; the same token gets forwarded to jobs via `--secrets HF_TOKEN`. `.env` at repo root already holds the token used by the pre-push HF Space hooks — same token works for Jobs.

## Maintenance

References are self-contained — no live URLs read at runtime. When the HF docs shift (new flavor, CLI flag rename), refresh the file rather than adding an external link. Keep each reference file under ~300 lines; split when concerns mix.
