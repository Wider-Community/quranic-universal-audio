"""TsJobSettings / TsJobRecord schema tests.

Pure ``extra="forbid"``: the retired ``persist_audio`` / ``gen_peaks`` knobs
(the timestamps job is alignment-only now — audio + peaks land offline) are
REJECTED on read rather than stripped. A clean settings/record round-trips.
"""

from __future__ import annotations

import pytest

from qua_shared.schemas import TsJobRecord, TsJobSettings


def test_settings_with_retired_persist_or_peaks_key_rejected():
    for retired in ("persist_audio", "gen_peaks"):
        with pytest.raises(ValueError):
            TsJobSettings.model_validate({"beams": [50, 2], "workers": 8, retired: True})


def test_clean_settings_validates():
    s = TsJobSettings.model_validate({"beams": [50, 2], "workers": 8})
    assert s.beams == [50, 2]
    assert s.workers == 8


def test_record_with_retired_settings_rejected():
    with pytest.raises(ValueError):
        TsJobRecord.model_validate(
            {
                "job_id": "j1",
                "slug": "minshawy_murattal",
                "settings": {"beams": [50], "persist_audio": True, "gen_peaks": True},
                "status": "succeeded",
            }
        )


def test_clean_record_validates():
    rec = TsJobRecord.model_validate(
        {
            "job_id": "j1",
            "slug": "minshawy_murattal",
            "settings": {"beams": [50]},
            "status": "succeeded",
        }
    )
    assert rec.settings.beams == [50]


def test_settings_default_beams_is_single_50():
    # The schema default stays a neutral resolved list; the launch form is the
    # single place that defaults probe beams to [2].
    assert TsJobSettings().beams == [50]
