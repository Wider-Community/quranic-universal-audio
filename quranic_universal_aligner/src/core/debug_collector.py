"""Thread-local debug data collector for the hidden debug API.

When active, pipeline stages append structured debug data to the collector
instead of (or in addition to) printing to stdout. The collector is the
single source of truth for the debug endpoint response.
"""

import threading

_ctx = threading.local()


class DebugCollector:
    """Accumulates structured debug data from all pipeline stages."""

    __slots__ = ("vad", "asr", "anchor", "specials", "alignment", "events", "_profiling")

    def __init__(self):
        self._profiling = None  # ProfilingData set by pipeline after completion
        self.vad = {}           # raw/cleaned intervals, counts, params
        self.asr = {}           # per-segment phonemes, model info
        self.anchor = {}        # voting results, surah ranking, best run
        self.specials = {       # special segment detection
            "candidates_tested": [],
            "detected": [],
            "first_quran_idx": 0,
        }
        self.alignment = []     # per-segment DP results
        self.events = []        # reanchors, chapter transitions, retries, gaps, etc.

    def add_event(self, event_type, **kwargs):
        """Append a pipeline event (gap, retry, reanchor, transition, etc.)."""
        self.events.append({"type": event_type, **kwargs})

    def add_special_candidate(self, segment_idx, candidate_type, edit_distance,
                              threshold, matched):
        """Record a special/transition detection attempt."""
        self.specials["candidates_tested"].append({
            "segment_idx": segment_idx,
            "type": candidate_type,
            "edit_distance": round(edit_distance, 4),
            "threshold": threshold,
            "matched": matched,
        })

    def add_special_detected(self, segment_idx, special_type, confidence):
        """Record a confirmed special segment detection."""
        self.specials["detected"].append({
            "segment_idx": segment_idx,
            "type": special_type,
            "confidence": round(confidence, 4),
        })

    def add_alignment_result(self, segment_idx, asr_phonemes, window,
                             expected_pointer, result=None, timing=None,
                             retry_tier=None, failed_reason=None):
        """Record a per-segment alignment result."""
        entry = {
            "segment_idx": segment_idx,
            "asr_phonemes": " ".join(asr_phonemes[:60]) + ("..." if len(asr_phonemes) > 60 else ""),
            "asr_phoneme_count": len(asr_phonemes),
            "window": window,
            "expected_pointer": expected_pointer,
            "retry_tier": retry_tier,
        }
        if result is not None:
            entry["result"] = result
        if timing is not None:
            entry["timing"] = {
                "window_setup_ms": round(timing.get("window_setup_time", 0) * 1000, 3),
                "dp_ms": round(timing.get("dp_time", 0) * 1000, 3),
                "result_build_ms": round(timing.get("result_build_time", 0) * 1000, 3),
            }
        if failed_reason is not None:
            entry["failed_reason"] = failed_reason
        self.alignment.append(entry)

    def to_dict(self):
        """Serialize collector to JSON-safe dict."""
        return {
            "vad": self.vad,
            "asr": self.asr,
            "anchor": self.anchor,
            "specials": self.specials,
            "alignment_detail": self.alignment,
            "events": self.events,
        }


def start_debug_collection():
    """Activate a DebugCollector for the current thread."""
    _ctx.collector = DebugCollector()


def get_debug_collector():
    """Return the active collector, or None if not in debug mode."""
    return getattr(_ctx, "collector", None)


def stop_debug_collection():
    """Deactivate and return the collector for the current thread."""
    c = getattr(_ctx, "collector", None)
    _ctx.collector = None
    return c
