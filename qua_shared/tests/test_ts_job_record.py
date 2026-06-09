"""TsJobSettings / TsJobRecord schema tests.

Focus: forward-compat for the retired ``persist_audio`` / ``gen_peaks`` knobs.
The timestamps job is now alignment-only (audio + peaks land offline), but old
on-disk records at ``reciters/<slug>/jobs/ts/<id>.json`` still nest those keys.
They must strip-with-warn on read, not fail ``extra="forbid"`` validation.
"""

from __future__ import annotations

from qua_shared.schemas import TsJobRecord, TsJobSettings


def test_settings_strips_retired_persist_and_peaks_keys():
    s = TsJobSettings.model_validate(
        {"beams": [50, 2], "persist_audio": True, "gen_peaks": False, "workers": 8}
    )
    assert s.beams == [50, 2]
    assert s.workers == 8
    assert not hasattr(s, "persist_audio")
    assert not hasattr(s, "gen_peaks")


def test_record_with_legacy_settings_still_parses():
    rec = TsJobRecord.model_validate(
        {
            "job_id": "j1",
            "slug": "minshawy_murattal",
            "settings": {"beams": [50], "persist_audio": True, "gen_peaks": True},
            "status": "succeeded",
        }
    )
    assert rec.settings.beams == [50]
    assert "persist_audio" not in rec.settings.model_dump()


def test_settings_default_beams_is_single_50():
    # The schema default stays a neutral resolved list; the launch form is the
    # single place that defaults probe beams to [2].
    assert TsJobSettings().beams == [50]
