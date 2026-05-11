"""Bootstrap the first OWNER member into ``<bucket>/access/inspector_roles.json``.

Usage:

    python -m scripts.inspector_v2_seed.bootstrap_access \
        --hf-user-id <hf_user_id> --login <hf_login>

Refuses to run if the roles file already has any active members.
"""

from __future__ import annotations

import argparse
import sys

from ._env import load_repo_env

load_repo_env()

from inspector.services import access


def main() -> int:
    parser = argparse.ArgumentParser(prog="bootstrap_access")
    parser.add_argument("--hf-user-id", required=True)
    parser.add_argument("--login", required=True)
    args = parser.parse_args()

    try:
        member = access.bootstrap(hf_user_id=args.hf_user_id, login=args.login)
    except access.AccessError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(
        f"ok  bootstrapped OWNER hf_user_id={member.hf_user_id} login={member.login}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
