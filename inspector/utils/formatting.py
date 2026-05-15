"""Display formatting utilities."""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return current UTC time as ISO string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def slug_to_name(slug: str) -> str:
    """Convert a slug like 'ali_jaber' to title case 'Ali Jaber'."""
    return slug.replace("_", " ").title()


def format_ms(ms) -> str:
    """Format milliseconds as m:ss."""
    total_sec = ms / 1000
    mins = int(total_sec // 60)
    secs = int(total_sec % 60)
    return f"{mins}:{secs:02d}"
