"""System actor for automation-launched actions (audit actor + ``launched_by``).

Every automated launch / config write carries this actor so the
*actor-on-every-edit* invariant holds and the activity rail clearly reads
"automation" (distinct from the manual ``SYSTEM_ACTOR`` used by webhook
completion handlers).
"""

from __future__ import annotations

from qua_shared.schemas import Actor, Role

#: Audit / launched_by id for automation-driven actions.
SYSTEM_AUTOMATION_ID = "SYSTEM_AUTOMATION"


def system_actor() -> Actor:
    """The automation system actor (owner-tier, synthetic id)."""
    return Actor(hf_user_id=SYSTEM_AUTOMATION_ID, login_at_time="system", role=Role.OWNER)
