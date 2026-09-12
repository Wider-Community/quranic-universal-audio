"""Native align pipeline — one click in the Requests tab, four stages on existing Spaces.

    acquire   CPU HF Job (``qua_jobs/acquire_audio.py``) persists chapter audio +
              peaks to ``reciters/<slug>/{audio,peaks}/``.
    align     per-chapter loop against the aligner Space's ``/api/v1/batches``
              (alignment-only, ``audio_ref=hf://buckets/…``), raw results staged
              under ``staging/<slug>/<run>/chapters/``.
    sidecars  one reciter-wide ``/api/v1/extraction/sidecars`` call (low-confidence
              probe + auto-split cursors, MFA on the phoneme Space).
    assemble  in-process ``promote_build`` → ``reciters/<slug>/{detailed,segments,
              …}``; ``auto_detect`` then fires ``alignment_completed``.

``runs`` is the public surface (start / retry / cancel / status); ``runner`` owns
the worker threads; the ``stage_*`` modules are the stages; ``adapt`` turns the
aligner's public rows into the staged-run shapes ``promote_build`` reads.
See ``docs/reference/align-pipeline.md``.
"""
