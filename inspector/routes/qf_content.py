"""Quran.Foundation Content-API read proxy (/api/qf/content/*).

Currently exposes word-by-word translations for the Timestamps tab's Analysis
view. Read-only GET routes (no CSRF / same-origin needed). The heavy lifting —
OAuth token, Cloudflare-safe UA, per-(verse,language) caching — lives in
``services/quran_foundation/content.py``.
"""

import logging

from flask import Blueprint, jsonify, request

from routes._riwayah_param import sdk_riwayah_param
from services.quran_foundation import config as qf_config
from services.quran_foundation import content as qf_content
from services.reference.editions import EditionsUnavailable

logger = logging.getLogger(__name__)

qf_content_bp = Blueprint("qf_content", __name__, url_prefix="/api/qf/content")


@qf_content_bp.route("/wbw/languages")
def wbw_languages():
    """Return the available word-by-word translation languages.

    ``complete`` is False for languages with meaningful English-fallback gaps
    (measured full-Quran); the picker flags those as "partial".
    """
    langs = [
        {"code": c, "label": label, "complete": c in qf_content.COMPLETE_WBW_CODES}
        for c, label in qf_content.CONTENT_WBW_LANGUAGES
    ]
    return jsonify(langs), 200, {"Cache-Control": "public, max-age=3600"}


@qf_content_bp.route("/wbw/<int:surah>/<int:ayah>")
def wbw(surah: int, ayah: int):
    """Return ``{location: gloss}`` word-by-word translation for one ayah.

    ``?riwayah=`` names the edition the coordinates belong to (Inspector slug;
    absent means Hafs). Glosses live in Hafs coordinates upstream, so a
    non-Hafs request is reverse-projected server-side and comes back keyed to
    the requested edition — the FE joins on ``TsWord.location`` either way.
    """
    if not qf_config.content_is_configured():
        return jsonify({"error": "content api not configured"}), 503
    lang = (request.args.get("language") or "en").strip()
    riwayah = sdk_riwayah_param(request.args.get("riwayah"))
    verse_key = f"{surah}:{ayah}"
    try:
        words = qf_content.word_by_word(verse_key, lang, riwayah)
    except EditionsUnavailable as e:
        logger.warning("qf-wbw: %s riwayah=%s unavailable: %s", verse_key, riwayah, e)
        return jsonify({"error": str(e)}), 503
    except qf_content.VerseNotInEdition as e:
        # A coordinate this edition does not have is the caller's error, not the
        # upstream API's — 502 would send an operator hunting a healthy service.
        logger.info("qf-wbw: %s riwayah=%s: %s", verse_key, riwayah, e)
        return jsonify({"error": str(e)}), 404
    except qf_content.QfContentError as e:
        logger.warning("qf-wbw: %s lang=%s failed: %s", verse_key, lang, e)
        return jsonify({"error": str(e)}), 502
    return jsonify({"verse_key": verse_key, "language": lang, "riwayah": riwayah, "words": words})
