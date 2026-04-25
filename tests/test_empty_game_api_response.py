"""Regression test: API returns empty/non-JSON body for a gamecode that doesn't exist.

Scenario (observed in E2021 ingestion, gamecodes ~156-300):
  - Euroleague API returns 200 OK but with an empty body or HTML for gamecodes
    that correspond to playoff slots that were never played.
  - r.json() raises requests.exceptions.JSONDecodeError (a subclass of RequestException).
  - season_sync._classify_error() treats all RequestException as "transient" →
    retries spiral, failure budget burns, sync stops early.

Expected behaviour after fix:
  - safe_json_get returns {} (or None) when the API returns non-JSON.
  - fetch_sources detects "no game data" and raises a ValueError.
  - _classify_error classifies "game not available" ValueError as permanent →
    the gamecode is skipped cleanly without consuming the retry budget.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_empty_response() -> MagicMock:
    """Simulate a 200 OK response whose body is not valid JSON (empty or HTML)."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    # Use stdlib JSONDecodeError (requests wraps it but constructor differs across versions)
    import json as _json
    resp.json.side_effect = _json.JSONDecodeError("No JSON object could be decoded", "", 0)
    return resp


# ── Test 1: safe_json_get returns {} for empty body (no exception propagated) ─

def test_safe_json_get_returns_empty_dict_on_non_json_response():
    """safe_json_get must NOT raise JSONDecodeError; it should return {} instead."""
    from build_from_euroleague_api import safe_json_get

    with patch("requests.get", return_value=_make_empty_response()):
        result = safe_json_get("http://fake-api/PlaybyPlay", {"seasoncode": "E2021", "gamecode": 167})

    assert result == {} or result is None, (
        f"Expected empty dict or None for non-JSON API response, got {result!r}"
    )


# ── Test 2: fetch_sources raises a ValueError (not JSONDecodeError) when both  ─
#           primary sources (PBP + Points) are empty.                             ─

def test_fetch_sources_raises_value_error_when_no_game_data(tmp_path):
    """When both PBP and Points return empty, fetch_sources must raise ValueError."""
    from build_from_euroleague_api import fetch_sources
    import os

    with patch("requests.get", return_value=_make_empty_response()), \
         patch.dict("os.environ", {"BASKET_APP_FILE_STORE_URI": str(tmp_path)}):
        with pytest.raises(ValueError, match="game not available"):
            fetch_sources("E2021", 167)


# ── Test 3: _classify_error treats that ValueError as permanent (skip, no retry) ─

def test_classify_error_treats_missing_game_as_permanent():
    """'game not available' ValueError must be classified as permanent, not transient."""
    from season_sync import _classify_error

    exc = ValueError("game not available")
    kind, msg = _classify_error(exc)

    assert kind == "permanent", (
        f"Expected 'permanent' classification so the gamecode is skipped, got '{kind}': {msg}"
    )


# ── Test 4: end-to-end _build_one_game skips cleanly (no throw, returns ok=False) ─

def test_build_one_game_skips_cleanly_for_missing_gamecode(tmp_path):
    """_build_one_game must return ok=False with kind='permanent' for a missing game."""
    from season_sync import _build_one_game

    out_path = tmp_path / "multi_drilldown_real_data_E2021_167.json"

    with patch("requests.get", return_value=_make_empty_response()), \
         patch.dict("os.environ", {"BASKET_APP_FILE_STORE_URI": str(tmp_path)}):
        ok, meta, kind, msg = _build_one_game(
            seasoncode="E2021",
            gamecode=167,
            out_path=out_path,
        )

    assert ok is False
    assert kind == "permanent", f"Expected 'permanent', got '{kind}': {msg}"
    assert not out_path.exists(), "No output file should be written for a missing game"
