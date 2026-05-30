"""Machine-to-machine webhook routes (no OAuth, no CSRF).

Endpoints here authenticate with a shared secret header rather than the OAuth
identity cookie — they're called by background jobs / external systems, not
browsers. Keep them minimal and secret-gated.
"""
