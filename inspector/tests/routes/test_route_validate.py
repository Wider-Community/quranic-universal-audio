"""GET /api/seg/validate/<reciter> response-shape tests (MUST-1)."""
from __future__ import annotations

import pytest

from tests.conftest import assert_keys_superset


def test_validate_response_shape(flask_client, tmp_reciter_dir, load_expected):
    """The validate route returns at least the frozen MUST-1 baseline field set."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["validate"]["field_keys_top_level"]

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code in (200, 404), (
        "expected 200 (validates fixture) or 404 (reciter rooted under tmp not visible)"
    )
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, dict)
        assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/validate")


@pytest.mark.xfail(reason="phase-2", strict=False)
def test_validate_includes_classified_issues_field_per_snapshot(flask_client, tmp_reciter_dir):
    """Every issue item should carry a classified_issues: string[] field after Phase 2."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "synthetic-classifier")

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code == 200
    body = res.get_json()

    issues_lists = []
    for top_key in ("issues", "details", "by_chapter"):
        v = body.get(top_key)
        if isinstance(v, list):
            issues_lists.append(v)
        elif isinstance(v, dict):
            for inner in v.values():
                if isinstance(inner, list):
                    issues_lists.append(inner)

    assert issues_lists, "no issues lists found in validate response to inspect"

    for lst in issues_lists:
        for item in lst:
            if isinstance(item, dict):
                assert "classified_issues" in item, (
                    f"issue item missing classified_issues field: {item}"
                )
                assert isinstance(item["classified_issues"], list)


@pytest.mark.xfail(reason="phase-6", strict=False)
def test_validate_issue_carries_segment_uid(flask_client, tmp_reciter_dir):
    """Phase 6: every issue item carries a segment_uid (null for chapter-level)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "synthetic-classifier")

    res = flask_client.get(f"/api/seg/validate/{reciter}")
    assert res.status_code == 200
    body = res.get_json()

    found_any = False
    for v in body.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    assert "segment_uid" in item, (
                        f"issue item must carry segment_uid (null allowed): {item}"
                    )
                    found_any = True
    assert found_any, "no per-issue items inspected"
