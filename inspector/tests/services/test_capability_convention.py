"""Guard tests for the capability convention (docs/reference/capabilities.md).

These keep "a new permission gate automatically surfaces in the Permissions
tab" true by construction:

1. The admin matrix renders EVERY registered capability — so a freshly
   registered capability can never silently fail to appear in the UI (the FE
   renders whatever the matrix returns).
2. No route uses the legacy ``@require_role`` decorator — new route gates must
   use ``@require_capability``, which validates its id against the registry at
   import time, forcing registration (and thus UI surfacing).
"""

from __future__ import annotations

from pathlib import Path

from qua_shared.schemas import CAPABILITIES_BY_ID

_ROUTES_DIR = Path(__file__).resolve().parents[1] / "routes"


def test_matrix_renders_every_registered_capability():
    """Registry → matrix → UI completeness: build_matrix() must surface every
    capability id. (The Permissions compartment renders the matrix verbatim, so
    this is the guarantee that a registered cap appears in the tab.)"""
    from services.admin import permissions as permissions_service

    matrix = permissions_service.build_matrix()
    rendered = {cap.id for group in matrix.groups for cap in group.capabilities}
    assert rendered == set(CAPABILITIES_BY_ID), (
        "Permissions matrix is out of sync with the registry: "
        f"missing={set(CAPABILITIES_BY_ID) - rendered}, "
        f"extra={rendered - set(CAPABILITIES_BY_ID)}"
    )


def test_no_require_role_decorator_in_routes():
    """New route gates must use @require_capability (data-driven, surfaces in
    the Permissions tab), never the legacy @require_role. Docstring mentions
    (``@require_role``) are ignored — only an actual decorator line counts."""
    offenders: list[str] = []
    for path in _ROUTES_DIR.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("@require_role("):
                offenders.append(f"{path.relative_to(_ROUTES_DIR.parent)}:{i}")
    assert not offenders, (
        "Use @require_capability(...) instead of @require_role(...) so the gate "
        f"surfaces in the Permissions tab. Offenders: {offenders}"
    )
