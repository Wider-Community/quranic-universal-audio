"""Inspector route blueprints."""


def register_blueprints(app):
    """Register all route blueprints on the Flask app."""
    from routes.timestamps import ts_bp
    from routes.segments_data import seg_data_bp
    from routes.segments_edit import seg_edit_bp
    from routes.segments_validation import seg_val_bp
    from routes.peaks import peaks_bp
    from routes.audio_proxy import audio_proxy_bp
    from routes.audio_metadata import audio_meta_bp

    app.register_blueprint(ts_bp)
    app.register_blueprint(seg_data_bp)
    app.register_blueprint(seg_edit_bp)
    app.register_blueprint(seg_val_bp)
    app.register_blueprint(peaks_bp)
    app.register_blueprint(audio_proxy_bp)
    app.register_blueprint(audio_meta_bp)
