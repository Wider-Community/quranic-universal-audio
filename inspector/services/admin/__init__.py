"""Admin-dashboard services: per-user read models + site visitor analytics.

Flask-free, like the rest of ``services/``. ``users`` assembles the admin
Users-panel read models from the substrate; ``visitors`` owns identity-recency
(debounced ``/api/me`` touch) plus the in-memory traffic counters and their
hourly flush daemon.
"""
