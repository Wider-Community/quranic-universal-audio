"""Quran.Foundation API integration (User APIs).

Backend-proxy pattern: per-user OAuth2 tokens stay server-side in a signed
``qf_session`` cookie; the browser never sees them. Outbound calls to QF
inject ``x-auth-token`` + ``x-client-id`` (see ``bookmarks.py``).

Two-environment split (QF docs warn never to mix tokens across them):
- User APIs (bookmarks) use the **pre-prod** client + ``apis-prelive`` base.
- Content APIs (separate, not wired here yet) use the **prod** client.

Flask-free by convention — routes (``routes/qf_auth.py``, ``routes/bookmarks.py``)
are the only layer that imports Flask.
"""
