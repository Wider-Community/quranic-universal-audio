"""Resolve subscribers per event, render, and dispatch — best-effort.

One function per event. Each reads the subscription rows, filters by the prefs
opt-ins, and submits a personalized email (its own manage / unsubscribe links)
to the sender pool. A publish can match several opt-ins for one address; it
collapses to a SINGLE email with precedence
``riwayah_first_available > riwayah_new_recitation > recitation_published``.

The two high-volume events — the ``recitation_published`` scope and
``timestamps_regenerated`` — are NOT sent immediately: they buffer per recipient
in ``email_digest`` and a background sweep (``services.email.digest``) flushes
each as one batched email per 60-min window, so a burst doesn't spam. The
riwayah-follow flavors stay immediate (lower frequency). Buffering rides
``durable_transaction`` (nesting-safe): inside the publish transition it adds no
extra bucket upload; the TS path is its own top-level write.

Per-recipient unsubscribe links mean no BCC batching — one message per address.
The subscriber set is small and sends are backgrounded, so this is fine.

Every function is wrapped in try/except-log: a lost notification email must never
break the motivating transition or job completion.
"""

from __future__ import annotations

import logging

import config

from . import send, templates

logger = logging.getLogger("email")


def _link_ctx(token: str) -> dict:
    base = config.EMAIL_APP_BASE_URL.rstrip("/")
    return {
        "site_url": config.EMAIL_SITE_URL,
        "manage_url": f"{base}/?manage={token}",
        "unsubscribe_url": f"{base}/api/email-unsubscribe?token={token}",
        "gh_releases_url": config.EMAIL_GH_RELEASES_URL,
    }


def _riwayah_label(slug: str | None) -> str:
    if not slug:
        return "this riwayah"
    return slug.replace("_", " ").replace("-", " ").title()


def _dispatch(sub: dict, event: str, extra_ctx: dict) -> None:
    ctx = {**_link_ctx(sub["manage_token"]), **extra_ctx}
    subject, html = templates.render(event, ctx)
    send.send(sub["email"], subject, html)


def _all() -> list[dict]:
    from services.db import repo_email_subscriptions as repo_subs

    return repo_subs.all_subscriptions()


def emit_request_aligned(*, hf_user_id: str | None, reciter_name: str) -> None:
    """The requester's alignment finished — email them if they opted in. Only
    matches a subscription carrying their ``hf_user_id`` (requests need identity)."""
    try:
        if not hf_user_id:
            return
        from services.db import repo_email_subscriptions as repo_subs

        sub = repo_subs.get_by_hf_user(hf_user_id)
        if sub is None or not sub["prefs"].get("request_aligned"):
            return
        _dispatch(sub, "request_aligned", {"reciter_name": reciter_name})
    except Exception:  # noqa: BLE001
        logger.exception("email.emit_request_aligned failed (hf_user_id=%s)", hf_user_id)


def _choose_publish_event(
    prefs: dict, reciter_id: str, riwayah: str | None, is_first_in_riwayah: bool
) -> str | None:
    follows = bool(riwayah) and riwayah in (prefs.get("riwayahs") or [])
    if is_first_in_riwayah and follows and prefs.get("riwayah_first_available"):
        return "riwayah_first_available"
    if follows and prefs.get("riwayah_new_recitation"):
        return "riwayah_new_recitation"
    scope = prefs.get("recitation_published")
    if scope == "all":
        return "recitation_published"
    if scope == "selected" and reciter_id in (prefs.get("reciters") or []):
        return "recitation_published"
    return None


def _scope_matches(prefs: dict, key: str, reciter_id: str) -> bool:
    """``all`` matches everything; ``selected`` matches only chosen reciters."""
    scope = prefs.get(key)
    return scope == "all" or (scope == "selected" and reciter_id in (prefs.get("reciters") or []))


def emit_recitation_published(
    *, reciter_id: str, reciter_name: str, riwayah: str | None, is_first_in_riwayah: bool
) -> None:
    """A recitation was published. Riwayah-follow matches send immediately; the
    plain ``recitation_published`` scope matches buffer into the 60-min digest."""
    try:
        from services.db import repo_email_digest
        from services.db import sync as _sync

        riwayah_label = _riwayah_label(riwayah)
        to_buffer: list[dict] = []
        for sub in _all():
            event = _choose_publish_event(sub["prefs"], reciter_id, riwayah, is_first_in_riwayah)
            if event is None:
                continue
            if event == "recitation_published":
                to_buffer.append(sub)
            else:  # riwayah_new_recitation / riwayah_first_available — immediate
                _dispatch(sub, event, {"reciter_name": reciter_name, "riwayah_label": riwayah_label})
        if to_buffer:
            with _sync.durable_transaction():
                for sub in to_buffer:
                    repo_email_digest.add(
                        email=sub["email"],
                        manage_token=sub["manage_token"],
                        event_kind="recitation_published",
                        reciter_id=reciter_id,
                        reciter_name=reciter_name,
                    )
    except Exception:  # noqa: BLE001
        logger.exception("email.emit_recitation_published failed (reciter_id=%s)", reciter_id)


def emit_timestamps_regenerated(*, reciter_id: str, reciter_name: str) -> None:
    """Timestamps regenerated for a released recitation — buffer opted-in
    followers into the 60-min digest (works for both ``all`` and ``selected``)."""
    try:
        from services.db import repo_email_digest
        from services.db import sync as _sync

        to_buffer = [
            sub for sub in _all() if _scope_matches(sub["prefs"], "timestamps_regenerated", reciter_id)
        ]
        if to_buffer:
            with _sync.durable_transaction():
                for sub in to_buffer:
                    repo_email_digest.add(
                        email=sub["email"],
                        manage_token=sub["manage_token"],
                        event_kind="timestamps_regenerated",
                        reciter_id=reciter_id,
                        reciter_name=reciter_name,
                    )
    except Exception:  # noqa: BLE001
        logger.exception("email.emit_timestamps_regenerated failed (reciter_id=%s)", reciter_id)


def _released_slugs() -> set[str]:
    from services.db import repo_state

    return {row.slug for row in repo_state.all_rows() if row.state.value == "released"}


def notify_recitation_published(slug: str) -> None:
    """Resolve a just-published slug → reciter_id / name / riwayah + whether it's
    the riwayah's first published recitation, then fan out. Resolution + send are
    best-effort. Reads see the in-transaction (uncommitted) released state."""
    try:
        from services.state import catalog

        delivery = catalog.find_delivery(slug)
        if delivery is None:
            return
        name = catalog.display_name(slug) or slug
        riwayah = getattr(delivery, "riwayah", None)
        is_first = False
        if riwayah:
            riwayah_slugs = {
                d.slug
                for d in catalog.snapshot().deliveries
                if getattr(d, "riwayah", None) == riwayah
            }
            released = _released_slugs() & riwayah_slugs
            is_first = released <= {slug}
        emit_recitation_published(
            reciter_id=delivery.reciter_id,
            reciter_name=name,
            riwayah=riwayah,
            is_first_in_riwayah=is_first,
        )
    except Exception:  # noqa: BLE001
        logger.exception("email.notify_recitation_published failed (slug=%s)", slug)


def notify_request_aligned(slug: str, hf_user_id: str | None) -> None:
    """Resolve a just-aligned slug → reciter name, then email the requester."""
    try:
        from services.state import catalog

        emit_request_aligned(hf_user_id=hf_user_id, reciter_name=catalog.display_name(slug) or slug)
    except Exception:  # noqa: BLE001
        logger.exception("email.notify_request_aligned failed (slug=%s)", slug)


def emit_github_release(*, version: str) -> None:
    """A new GitHub release was cut — email everyone subscribed to releases. The
    body always links the releases index page (per product decision)."""
    try:
        for sub in _all():
            if sub["prefs"].get("github_release"):
                _dispatch(sub, "github_release", {"version": version})
    except Exception:  # noqa: BLE001
        logger.exception("email.emit_github_release failed (version=%s)", version)
