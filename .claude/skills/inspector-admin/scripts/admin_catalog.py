"""Catalog admin CLI — read + mutate the full reciter catalog.

Thin wrapper over ``inspector/services/state/catalog.py`` (the sole catalog
writer the UI also calls): no parallel logic, no schema drift. Every write is
capability-gated (``catalog.add`` / ``catalog.edit``), audited (``catalog.*``),
and runs inside ``durable_transaction`` — an in-process bucket-DB write, so on
prod the whole op runs inside ``prod_safe_setup`` (Space paused, single-writer)
via ``bs.run(..., safe_write=True)``.

Entities × actions::

    reciter  list | show <reciter_id> | add <reciter_id> --name-en ...
                  | edit <reciter_id> [--name-en/--name-ar/--country/--notes]
    delivery list [--reciter ID] | show <slug>
                  | add <slug> --reciter-id --riwayah --style --source
                        --channel --audio-category --chapter-count [...]
                  | edit <slug> [--riwayah/--style/--recording-context/--recording-year]
    source   list | add <slug> --name [--url --categories by_surah,by_ayah]
    channel  list | add <slug> --short --name [--host-patterns --gh-release-eligible]
    vocab    show                           # riwayat / styles / sources / channels / contexts

Reads need neither actor nor --yes-prod. Writes need --yes-prod on prod; the
delivery/reciter ``edit`` surface mirrors the service's narrow public surface
(broader row fields like audio metadata aren't service-editable by design —
use the probe pipeline / admin_db for those).

Examples::

    python admin_catalog.py delivery show mohammed_burhaji_yt --prod
    python admin_catalog.py delivery edit mohammed_burhaji_yt \\
        --recording-context studio --recording-year 2026 --prod --yes-prod
    python admin_catalog.py reciter edit mohammed_burhaji --country SA --prod --yes-prod
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import _bootstrap as bs
from _bootstrap import add_common_args

WRITE_ACTIONS = {"add", "edit"}


def _dump(model) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)


# ---- reciter ----


def _reciter_list(a, cat) -> int:
    for r in sorted(cat.reciters, key=lambda r: r.reciter_id):
        ar = f"  {r.name_ar}" if r.name_ar else ""
        print(f"{r.reciter_id:<40} {r.name_en}{ar}")
    print(f"\n{len(cat.reciters)} reciters")
    return 0


def _reciter_show(a, cat) -> int:
    from services.state import catalog

    r = catalog.find_reciter(a.reciter_id)
    if r is None:
        print(f"reciter_id {a.reciter_id!r} not found", file=sys.stderr)
        return 1
    print(_dump(r))
    deliveries = [d for d in cat.deliveries if d.reciter_id == a.reciter_id]
    print(f"\ndeliveries ({len(deliveries)}):")
    for d in deliveries:
        print(f"  {d.slug:<44} {d.source}/{d.channel} {d.audio_category.value}")
    return 0


def _reciter_add(a, ctx) -> int:
    from services.state import catalog

    r = catalog.add_reciter(
        actor=ctx.actor, reciter_id=a.reciter_id, name_en=a.name_en,
        name_ar=a.name_ar, country=a.country, notes=a.notes, reason=a.reason,
    )
    print(f"added reciter {r.reciter_id}: {r.name_en}")
    return 0


def _reciter_edit(a, ctx) -> int:
    from services.state import catalog

    r = catalog.edit_reciter(
        actor=ctx.actor, reciter_id=a.reciter_id, name_en=a.name_en,
        name_ar=a.name_ar, country=a.country, notes=a.notes, reason=a.reason,
    )
    print(f"edited reciter {r.reciter_id}:")
    print(_dump(r))
    return 0


# ---- delivery ----


def _delivery_list(a, cat) -> int:
    rows = cat.deliveries
    if a.reciter:
        rows = [d for d in rows if d.reciter_id == a.reciter]
    for d in sorted(rows, key=lambda d: d.slug):
        ctxv = d.recording_context or "—"
        yr = d.recording_year or "—"
        print(f"{d.slug:<46} {d.riwayah}/{d.style}  ctx={ctxv} yr={yr}  {d.source}/{d.channel}")
    print(f"\n{len(rows)} deliveries")
    return 0


def _delivery_show(a, cat) -> int:
    from services.state import catalog

    d = catalog.find_delivery(a.slug)
    if d is None:
        print(f"delivery slug {a.slug!r} not found", file=sys.stderr)
        return 1
    print(_dump(d))
    return 0


def _delivery_add(a, ctx) -> int:
    from services.state import catalog
    from qua_shared.schemas import Delivery

    delivery = Delivery(
        slug=a.slug, reciter_id=a.reciter_id, riwayah=a.riwayah, style=a.style,
        recording_context=a.recording_context, recording_year=a.recording_year,
        variant_label=a.variant_label, source=a.source, channel=a.channel,
        source_url=a.source_url, audio_category=a.audio_category,
        chapter_count=a.chapter_count, sample_rate_hz=a.sample_rate_hz,
        channels=a.channels, bitrate_mode=a.bitrate_mode,
        bitrate_kbps_nominal=a.bitrate_kbps_nominal,
        total_duration_sec=a.total_duration_sec,
        added_at=datetime.now(timezone.utc), added_by_hf_id=ctx.actor.hf_user_id,
    )
    d = catalog.add_delivery(actor=ctx.actor, delivery=delivery, reason=a.reason)
    print(f"added delivery {d.slug} (reciter {d.reciter_id})")
    return 0


def _delivery_edit(a, ctx) -> int:
    from services.state import catalog

    d = catalog.edit_delivery(
        actor=ctx.actor, slug=a.slug, riwayah=a.riwayah, style=a.style,
        recording_context=a.recording_context, recording_year=a.recording_year,
        reason=a.reason,
    )
    print(f"edited delivery {d.slug}:")
    print(_dump(d))
    return 0


# ---- source / channel / vocab ----


def _source_list(a, cat) -> int:
    for s in sorted(cat.vocab.sources, key=lambda s: s.slug):
        cats = ",".join(c.value for c in s.audio_categories) or "—"
        print(f"{s.slug:<24} {s.name:<32} {s.url or '—'}  [{cats}]")
    print(f"\n{len(cat.vocab.sources)} sources")
    return 0


def _source_add(a, ctx) -> int:
    from services.state import catalog
    from qua_shared.schemas import Source

    cats = [c.strip() for c in (a.categories or "").split(",") if c.strip()]
    src = Source(slug=a.slug, name=a.name, url=a.url, audio_categories=cats)
    s = catalog.add_audio_source(actor=ctx.actor, source=src, reason=a.reason)
    print(f"added source {s.slug}: {s.name}")
    return 0


def _channel_list(a, cat) -> int:
    for c in sorted(cat.vocab.channels, key=lambda c: c.slug):
        pat = ",".join(c.host_patterns) or "—"
        gh = "gh" if c.gh_release_eligible else ""
        print(f"{c.slug:<20} short={c.short:<10} {c.name:<28} {pat} {gh}")
    print(f"\n{len(cat.vocab.channels)} channels")
    return 0


def _channel_add(a, ctx) -> int:
    from services.state import catalog
    from qua_shared.schemas import Channel

    patterns = [p.strip() for p in (a.host_patterns or "").split(",") if p.strip()]
    ch = Channel(slug=a.slug, short=a.short, name=a.name,
                 host_patterns=patterns, gh_release_eligible=a.gh_release_eligible)
    c = catalog.add_channel(actor=ctx.actor, channel=ch, reason=a.reason)
    print(f"added channel {c.slug} (short={c.short}): {c.name}")
    return 0


def _vocab_show(a, cat) -> int:
    v = cat.vocab
    print("riwayat:")
    for r in v.riwayat:
        print(f"  {r.slug:<20} short={r.short:<8} {r.name}")
    print("styles:")
    for s in v.styles:
        print(f"  {s.slug:<20} short={s.short:<8} {s.name}")
    print("recording_contexts:")
    for c in v.recording_contexts:
        print(f"  {c.slug:<20} {c.name}")
    print(f"sources: {len(v.sources)}   channels: {len(v.channels)}  "
          f"(use `source list` / `channel list`)")
    return 0


# ---- dispatch ----

# action key -> (handler, is_write). Read handlers take (a, catalog_snapshot);
# write handlers take (a, ctx).
DISPATCH = {
    "reciter:list": (_reciter_list, False),
    "reciter:show": (_reciter_show, False),
    "reciter:add": (_reciter_add, True),
    "reciter:edit": (_reciter_edit, True),
    "delivery:list": (_delivery_list, False),
    "delivery:show": (_delivery_show, False),
    "delivery:add": (_delivery_add, True),
    "delivery:edit": (_delivery_edit, True),
    "source:list": (_source_list, False),
    "source:add": (_source_add, True),
    "channel:list": (_channel_list, False),
    "channel:add": (_channel_add, True),
    "vocab:show": (_vocab_show, False),
}


def _leaf(p: argparse.ArgumentParser, *, write: bool) -> argparse.ArgumentParser:
    add_common_args(p, mutating=write)
    if write:
        p.add_argument("--reason")
    return p


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read + mutate the reciter catalog.")
    ent = p.add_subparsers(dest="entity", required=True)

    # reciter
    rec = ent.add_parser("reciter").add_subparsers(dest="action", required=True)
    _leaf(rec.add_parser("list"), write=False)
    _leaf(rec.add_parser("show"), write=False).add_argument("reciter_id")
    for name in ("add", "edit"):
        sp = _leaf(rec.add_parser(name), write=True)
        sp.add_argument("reciter_id")
        sp.add_argument("--name-en", dest="name_en",
                        required=(name == "add"))
        sp.add_argument("--name-ar", dest="name_ar")
        sp.add_argument("--country")
        sp.add_argument("--notes")

    # delivery
    dlv = ent.add_parser("delivery").add_subparsers(dest="action", required=True)
    dl = _leaf(dlv.add_parser("list"), write=False)
    dl.add_argument("--reciter")
    _leaf(dlv.add_parser("show"), write=False).add_argument("slug")
    da = _leaf(dlv.add_parser("add"), write=True)
    da.add_argument("slug")
    da.add_argument("--reciter-id", dest="reciter_id", required=True)
    da.add_argument("--riwayah", required=True)
    da.add_argument("--style", required=True)
    da.add_argument("--source", required=True)
    da.add_argument("--channel", required=True)
    da.add_argument("--audio-category", dest="audio_category",
                    choices=["by_surah", "by_ayah"], required=True)
    da.add_argument("--chapter-count", dest="chapter_count", type=int, required=True)
    da.add_argument("--recording-context", dest="recording_context")
    da.add_argument("--recording-year", dest="recording_year", type=int)
    da.add_argument("--variant-label", dest="variant_label")
    da.add_argument("--source-url", dest="source_url")
    da.add_argument("--sample-rate-hz", dest="sample_rate_hz", type=int)
    da.add_argument("--channels", type=int)
    da.add_argument("--bitrate-mode", dest="bitrate_mode",
                    choices=["cbr", "vbr", "mixed", "unknown"], default="unknown")
    da.add_argument("--bitrate-kbps-nominal", dest="bitrate_kbps_nominal", type=int)
    da.add_argument("--total-duration-sec", dest="total_duration_sec", type=int)
    de = _leaf(dlv.add_parser("edit"), write=True)
    de.add_argument("slug")
    de.add_argument("--riwayah")
    de.add_argument("--style")
    de.add_argument("--recording-context", dest="recording_context")
    de.add_argument("--recording-year", dest="recording_year", type=int)

    # source
    src = ent.add_parser("source").add_subparsers(dest="action", required=True)
    _leaf(src.add_parser("list"), write=False)
    sa = _leaf(src.add_parser("add"), write=True)
    sa.add_argument("slug")
    sa.add_argument("--name", required=True)
    sa.add_argument("--url")
    sa.add_argument("--categories", help="comma-separated: by_surah,by_ayah")

    # channel
    chn = ent.add_parser("channel").add_subparsers(dest="action", required=True)
    _leaf(chn.add_parser("list"), write=False)
    ca = _leaf(chn.add_parser("add"), write=True)
    ca.add_argument("slug")
    ca.add_argument("--short", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--host-patterns", dest="host_patterns",
                    help="comma-separated host globs")
    ca.add_argument("--gh-release-eligible", dest="gh_release_eligible",
                    action="store_true")

    # vocab
    voc = ent.add_parser("vocab").add_subparsers(dest="action", required=True)
    _leaf(voc.add_parser("show"), write=False)

    return p


def main() -> int:
    a = _build_parser().parse_args()
    key = f"{a.entity}:{a.action}"
    handler, is_write = DISPATCH[key]

    def run_handler(ctx: bs.BootstrapCtx) -> int:
        if is_write:
            if getattr(a, "dry_run", False):
                print(f"[dry-run] would run {key} ({a})")
                return 0
            rc = handler(a, ctx)
            bs.after_write_banner(a)
            return rc
        from services.state import catalog
        return handler(a, catalog.snapshot())

    return bs.run(a, run_handler, need_actor=is_write,
                  mutates=is_write, safe_write=is_write)


if __name__ == "__main__":
    raise SystemExit(main())
