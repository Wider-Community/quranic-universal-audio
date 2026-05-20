"""Maps our ``(reciter_id, style)`` to a Quran.Foundation chapter-reciter id.

Only reciters we verified exist in the QF ``chapter_reciters`` set (full-surah
audio, all served from ``download.quranicaudio.com``). Used by the dashboard
audio route to route playback of our QuranicAudio-source deliveries through the
Content API. Extend as more reciters are confirmed (e.g. husary ``muallim`` 12).
"""

from __future__ import annotations

from typing import Final

QF_CHAPTER_RECITER_MAP: Final[dict[tuple[str, str], int]] = {
    ("abdulbasit_abdulsamad", "murattal"): 2,
    ("abdulbasit_abdulsamad", "mujawwad"): 1,
    ("abdulrahman_al_sudais", "murattal"): 3,
    ("abu_bakr_al_shatri", "murattal"): 4,
    ("hani_al_rifai", "murattal"): 5,
    ("mahmoud_khalil_al_husary", "murattal"): 6,
    ("saad_al_ghamdi", "murattal"): 13,
    ("ahmed_al_ajmi", "murattal"): 19,
    ("abdullah_ali_jabir", "murattal"): 158,
    ("bandar_baleela", "murattal"): 160,
    ("maher_al_muaiqly", "murattal"): 159,
    ("mishary_rashid_al_afasy", "murattal"): 7,
    ("mohammed_siddiq_al_minshawi", "murattal"): 9,
    ("saud_al_shuraim", "murattal"): 10,
    ("khalifa_al_tunaiji", "murattal"): 161,
    ("yasser_al_dosari", "murattal"): 174,
}


def qf_id_for(reciter_id: str, style: str | None) -> int | None:
    """Return the QF chapter-reciter id for a delivery, or ``None``."""
    if not reciter_id or not style:
        return None
    return QF_CHAPTER_RECITER_MAP.get((reciter_id, style))
