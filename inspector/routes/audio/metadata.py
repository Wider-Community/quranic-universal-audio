"""Audio tab metadata routes (/api/audio/*)."""

import logging

from flask import Blueprint, jsonify

from qua_shared.schemas import AudioSurahsResponse, ErrorEnvelope
from services import audio_fetch, cache, storage_paths
from services.hf_bucket import StorageNotFound, get_backend
from services.quran_foundation import config as qf_config
from services.quran_foundation import content as qf_content
from services.quran_foundation.reciter_map import qf_id_for
from services.state import catalog

logger = logging.getLogger(__name__)

audio_meta_bp = Blueprint("audio_meta", __name__, url_prefix="/api/audio")


def _apply_qf_routing(source: str, slug: str, surahs: dict[str, dict]) -> None:
    """Swap our QuranicAudio CDN links for Content-API URLs in place.

    Only acts on ``source == "quranicaudio"`` deliveries whose (reciter_id,
    style) is mapped. Each routed chapter is tagged ``via="qf_api"`` with the
    original link kept as ``origin_url`` (so the FE can log the override). On
    any Content-API failure the chapters keep our link, tagged ``qf_fallback``.
    """
    if source != "quranicaudio" or not qf_config.content_is_configured():
        return
    delivery = catalog.find_delivery(slug)
    if delivery is None:
        return
    qf_id = qf_id_for(delivery.reciter_id, delivery.style)
    if qf_id is None:
        return
    try:
        api_urls = qf_content.chapter_audio_urls(qf_id)
    except qf_content.QfContentError as e:
        logger.warning("qf-audio: routing failed for %s (qf id %s): %s", slug, qf_id, e)
        for entry in surahs.values():
            entry["via"] = "qf_fallback"
        return
    for k, entry in surahs.items():
        api_url = api_urls.get(k)
        if not api_url:
            continue
        entry["origin_url"] = entry["url"]
        entry["url"] = api_url
        entry["via"] = "qf_api"
        # The QF /qdc/ files are re-encodes of differing length; drop our
        # manifest duration so the player reads the real header on play.
        entry["duration_ms"] = None


@audio_meta_bp.route("/surahs/<category>/<source>/<slug>")
def audio_surahs(category, source, slug):
    """Return per-chapter ``{url, duration_ms}`` for a delivery.

    Reads the per-delivery audio_manifest sidecar from
    ``<bucket>/catalog/audio_manifest/<slug>.json``. ``duration_ms`` is
    derived from the sidecar's ``duration_sec`` so the dashboard player can
    show full chapter length before the browser fetches MP3 headers — the
    ``BottomPlayer`` runs ``<audio preload="none">`` and would otherwise
    show ``0:00`` until first play.

    When the sidecar has a null/missing duration for a chapter (e.g. probed
    before the manifest carried durations), falls back to the duration baked
    into the slim peaks header (``reciters/<slug>/peaks/<ch>.json.gz``) via
    ``audio_fetch.read_prefetched_peaks_duration_ms``. Stays ``None`` only
    when peaks are also absent.
    """
    key = f"{category}/{source}/{slug}"
    cached = cache.get_audio_url_cache(key)
    if cached is not None:
        return jsonify(_serialize_surahs(cached))
    try:
        doc = get_backend().read_json(storage_paths.audio_manifest_path(slug))
    except StorageNotFound:
        return jsonify(ErrorEnvelope(error="Reciter not found").model_dump(exclude_none=True)), 404
    if not isinstance(doc, dict):
        return (
            jsonify(
                ErrorEnvelope(error="invalid audio_manifest sidecar").model_dump(exclude_none=True)
            ),
            500,
        )
    chapters = doc.get("chapters") or {}
    surahs: dict[str, dict] = {}
    for k, v in chapters.items():
        if isinstance(v, dict):
            url = v.get("url")
            if not isinstance(url, str):
                continue
            duration_sec = v.get("duration_sec")
            duration_ms = (
                int(round(duration_sec * 1000)) if isinstance(duration_sec, (int, float)) else None
            )
        elif isinstance(v, str):
            url, duration_ms = v, None
        else:
            continue
        if duration_ms is None:
            # Manifest never carried a length for this chapter — fall back to
            # the duration baked into the slim peaks header so the dashboard
            # scrubber shows a real length instead of 0:00.
            duration_ms = audio_fetch.read_prefetched_peaks_duration_ms(slug, url)
        surahs[k] = {"url": url, "duration_ms": duration_ms}
    _apply_qf_routing(source, slug, surahs)
    cache.set_audio_url_cache(key, surahs)
    return jsonify(_serialize_surahs(surahs))


def _serialize_surahs(surahs: dict[str, dict]) -> dict:
    """Serialize the per-chapter ``surahs`` map through the wire model.

    Dumps with ``by_alias`` and no ``exclude_none``: ``AudioSurahEntry`` carries
    a serializer that drops only the optional QF keys (``via``/``origin_url``)
    when unset and always keeps the required-nullable ``duration_ms``.
    """
    return AudioSurahsResponse.model_validate({"surahs": surahs}).model_dump(by_alias=True)
