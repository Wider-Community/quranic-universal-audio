"""Inspector route blueprints.

``timestamps.ts_validate`` is gated route-level inside ``timestamps.py``
via ``INSPECTOR_TS_VALIDATE_ENABLED`` (the rest of ``ts_bp`` is always on).

``audio_proxy_bp`` is registered unconditionally because ``source.ts``
routes by_surah audio through ``/api/seg/audio-proxy/<reciter>?url=...``
and that route is the only thing standing between the user and broken
playback. The proxy degrades to a 302 redirect to the origin CDN when
no cache file exists, so the cost in deployed mode is one extra hop and
no background workers run unless the user explicitly POSTs to
``/prepare-audio``.
"""


def register_blueprints(app):
    """Register all route blueprints on the Flask app."""
    from routes.auth import auth_bp
    from routes.claims import claims_bp
    from routes.timestamps import ts_bp
    from routes.segments_data import seg_data_bp
    from routes.segments_edit import seg_edit_bp
    from routes.segments_validation import seg_val_bp
    from routes.peaks import peaks_bp
    from routes.audio_proxy import audio_proxy_bp
    from routes.audio_metadata import audio_meta_bp
    from routes.segment_clip import segment_clip_bp
    from routes.static_data import static_bp
    from routes.health import health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(ts_bp)
    app.register_blueprint(seg_data_bp)
    app.register_blueprint(seg_edit_bp)
    app.register_blueprint(seg_val_bp)
    app.register_blueprint(peaks_bp)
    app.register_blueprint(audio_proxy_bp)
    app.register_blueprint(audio_meta_bp)
    app.register_blueprint(segment_clip_bp)
    app.register_blueprint(static_bp)
