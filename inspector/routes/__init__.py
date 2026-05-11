"""Inspector route blueprints.

Two blueprints are env-gated for the deployed image surface:

- ``audio_proxy_bp`` mounts only when ``INSPECTOR_AUDIO_PROXY_ENABLED=1``
  (default ``1`` for local; flipped to ``0`` in the Dockerfile so the deployed
  Space doesn't expose the proxy or background download workers).
- ``timestamps.ts_validate`` is gated route-level inside ``timestamps.py``
  via ``INSPECTOR_TS_VALIDATE_ENABLED`` (the rest of ``ts_bp`` is always on).
"""

import os


def register_blueprints(app):
    """Register all route blueprints on the Flask app."""
    from routes.timestamps import ts_bp
    from routes.segments_data import seg_data_bp
    from routes.segments_edit import seg_edit_bp
    from routes.segments_validation import seg_val_bp
    from routes.peaks import peaks_bp
    from routes.audio_metadata import audio_meta_bp
    from routes.segment_clip import segment_clip_bp
    from routes.static_data import static_bp
    from routes.health import health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(ts_bp)
    app.register_blueprint(seg_data_bp)
    app.register_blueprint(seg_edit_bp)
    app.register_blueprint(seg_val_bp)
    app.register_blueprint(peaks_bp)
    app.register_blueprint(audio_meta_bp)
    app.register_blueprint(segment_clip_bp)
    app.register_blueprint(static_bp)

    if os.environ.get("INSPECTOR_AUDIO_PROXY_ENABLED", "1") == "1":
        from routes.audio_proxy import audio_proxy_bp
        app.register_blueprint(audio_proxy_bp)
