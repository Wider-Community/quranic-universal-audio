"""Start timestamp generation with the exact phonemizer producer installed.

The public prebuilt image is an optimization, not a dependency lock: it can
lag behind this checkout.  Keep this wrapper stdlib-only so it can repair that
environment before importing the real generator.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

PHONEMIZER_VERSION = "2.15.3"


def installed_phonemizer_version() -> str | None:
    try:
        return importlib.metadata.version("quranic-phonemizer")
    except importlib.metadata.PackageNotFoundError:
        return None


def ensure_phonemizer() -> None:
    """Install the pinned producer when the container image has drifted."""
    found = installed_phonemizer_version()
    if found == PHONEMIZER_VERSION:
        return
    print(
        f"timestamp runtime has quranic-phonemizer {found or 'missing'}; "
        f"installing {PHONEMIZER_VERSION}",
        flush=True,
    )
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            f"quranic-phonemizer=={PHONEMIZER_VERSION}",
        ]
    )


def main() -> None:
    ensure_phonemizer()
    generator = Path(__file__).with_name("generate_timestamps.py")
    os.execv(sys.executable, [sys.executable, str(generator), *sys.argv[1:]])


if __name__ == "__main__":
    main()
