"""Timestamps-tab backend services (report snapshot + staleness).

Flask-free domain logic for the categorized Timestamps reports feature. Shard
*serving* stays in ``services/reference/timestamps.py`` (a byte pass-through);
this package only reads/parses shards at the cold report-create + regeneration
paths to build/compare the per-report content snapshot.
"""
