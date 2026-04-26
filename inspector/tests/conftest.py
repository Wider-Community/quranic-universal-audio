"""Shared pytest fixtures for the inspector test suite.

The Flask app in ``inspector/app.py`` is constructed at module import time
(module-level ``app = Flask(...)``), not via a factory. Tests that need a
client spin one up via ``app.test_client()`` — see ``test_app_smoke.py``.
"""
