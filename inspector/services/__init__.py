"""Inspector service modules: business logic used by route blueprints.

Modules are organised into domain subpackages (``auth``, ``state``, ``storage``,
``audio``, ``activity``, ``segments``, ``reference``, ``validation``). This
``__init__`` re-exports every submodule at the legacy top-level name so
existing imports of the form ``from services.X import Y`` continue to work
without churn (consumers in routes/, app.py, tests/, bench/, scripts/).

When adding a new service module, drop it in the appropriate subpackage and
add a single re-export line below.
"""

from __future__ import annotations

import sys as _sys

from .auth import access, auth, hf_users, permissions, predicates, secrets_guard
from .state import audit, catalog, pending_requests, request_archive, state
from .storage import cache, data_dir, data_loader, hf_bucket, storage_paths
from .audio import (
    audio_fetch,
    audio_meta,
    audio_prefetch,
    audio_source,
    peaks,
    peaks_history,
    peaks_slim,
)
from .activity import (
    activity_classification,
    activity_state,
    history_query,
    public_activity,
    search_normalize,
    stats,
)
from .segments import (
    auto_detect,
    auto_split,
    qalqala,
    save,
    segments_query,
    undo,
)
from .reference import public_state, quran_refs, timestamps
from . import validation

# Alias each submodule into sys.modules under its legacy ``services.X`` name so
# existing ``from services.X import Y`` imports and ``monkeypatch.setattr(
# "services.X.fn", ...)`` test paths resolve to the moved modules.
_LEGACY_ALIASES = {
    "access": access,
    "auth": auth,
    "hf_users": hf_users,
    "permissions": permissions,
    "predicates": predicates,
    "secrets_guard": secrets_guard,
    "audit": audit,
    "catalog": catalog,
    "pending_requests": pending_requests,
    "request_archive": request_archive,
    "state": state,
    "cache": cache,
    "data_dir": data_dir,
    "data_loader": data_loader,
    "hf_bucket": hf_bucket,
    "storage_paths": storage_paths,
    "audio_fetch": audio_fetch,
    "audio_meta": audio_meta,
    "audio_prefetch": audio_prefetch,
    "audio_source": audio_source,
    "peaks": peaks,
    "peaks_history": peaks_history,
    "activity_classification": activity_classification,
    "activity_state": activity_state,
    "history_query": history_query,
    "public_activity": public_activity,
    "search_normalize": search_normalize,
    "stats": stats,
    "auto_detect": auto_detect,
    "auto_split": auto_split,
    "qalqala": qalqala,
    "save": save,
    "segments_query": segments_query,
    "undo": undo,
    "public_state": public_state,
    "quran_refs": quran_refs,
    "timestamps": timestamps,
}

# Register the alias under whichever name the package was imported as
# ("services" when inspector/ is on sys.path, or "inspector.services" when
# external callers do ``from inspector.services import X``).
for _name, _mod in _LEGACY_ALIASES.items():
    _sys.modules.setdefault(f"{__name__}.{_name}", _mod)

del _sys, _name, _mod, _LEGACY_ALIASES
