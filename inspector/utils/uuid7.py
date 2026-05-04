"""UUIDv7 generator (time-ordered, RFC 9562)."""

import time as _time
import uuid


def uuid7() -> str:
    """Generate a UUIDv7 (time-ordered, RFC 9562) as a hyphenated string."""
    ts_ms = int(_time.time() * 1000)
    rand_bytes = uuid.uuid4().bytes
    uuid_int = (ts_ms & 0xFFFFFFFFFFFF) << 80
    uuid_int |= 0x7000 << 64  # version 7
    uuid_int |= (int.from_bytes(rand_bytes[:2], "big") & 0x0FFF) << 64
    uuid_int |= 0x8000000000000000  # variant 10
    uuid_int |= int.from_bytes(rand_bytes[2:10], "big") & 0x3FFFFFFFFFFFFFFF
    return str(uuid.UUID(int=uuid_int))
