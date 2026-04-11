"""Display formatting utilities."""


def format_ms(ms) -> str:
    """Format milliseconds as m:ss."""
    total_sec = ms / 1000
    mins = int(total_sec // 60)
    secs = int(total_sec % 60)
    return f"{mins}:{secs:02d}"
