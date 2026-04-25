from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def elo_mod():
    from basket import elo

    return elo


def _write_game(path: Path, seasoncode: str, gamecode: int, team_a: str, team_b: str, score_a: int, score_b: int, gamedate: str) -> None:
    winner = team_a if score_a > score_b else (team_b if score_b > score_a else None)
    payload = {
        "meta": {
            "seasoncode": seasoncode,
            "gamecode": gamecode,
            "team_a": team_a,
            "team_b": team_b,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "gamedate": gamedate,
        }
    }
    file_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
    (path / file_name).write_text(json.dumps(payload), encoding="utf-8")


def test_recompute_multiseason_when_output_missing(tmp_path: Path, elo_mod) -> None:
    _write_game(tmp_path, "E2022", 1, "Alpha", "Beta", 80, 70, "2022-10-01T19:00:00Z")
    _write_game(tmp_path, "E2023", 1, "Alpha", "Gamma", 75, 82, "2023-10-03T19:00:00Z")

    should, seasons, reason = elo_mod.should_recompute_multiseason_elo(tmp_path)
    assert should is True
    assert seasons == ["E2022", "E2023"]
    assert "missing elo_multiseason.json" in reason

    recomputed, payload, status = elo_mod.recompute_multiseason_elo_if_needed(tmp_path)
    assert recomputed is True
    assert status == "recomputed"
    assert payload is not None
    assert payload["seasoncodes"] == ["E2022", "E2023"]
    assert len(payload["history"]) == 2
    assert (tmp_path / "elo_multiseason.json").exists()


def test_skip_recompute_when_already_up_to_date(tmp_path: Path, elo_mod) -> None:
    _write_game(tmp_path, "E2022", 1, "Alpha", "Beta", 80, 70, "2022-10-01T19:00:00Z")
    _write_game(tmp_path, "E2023", 1, "Alpha", "Gamma", 75, 82, "2023-10-03T19:00:00Z")

    first_recomputed, _payload, _status = elo_mod.recompute_multiseason_elo_if_needed(tmp_path)
    assert first_recomputed is True

    second_recomputed, second_payload, reason = elo_mod.recompute_multiseason_elo_if_needed(tmp_path)
    assert second_recomputed is False
    assert second_payload is None
    assert reason == "up-to-date"


def test_non_consecutive_stored_seasons_block_auto_recompute(tmp_path: Path, elo_mod) -> None:
    _write_game(tmp_path, "E2022", 1, "Alpha", "Beta", 80, 70, "2022-10-01T19:00:00Z")
    _write_game(tmp_path, "E2024", 1, "Alpha", "Gamma", 75, 82, "2024-10-03T19:00:00Z")

    should, seasons, reason = elo_mod.should_recompute_multiseason_elo(tmp_path)
    assert should is False
    assert seasons == ["E2022", "E2024"]
    assert "not consecutive" in reason
    assert "E2023" in reason

    with pytest.raises(ValueError):
        elo_mod.compute_elo_for_seasoncodes(tmp_path, ["E2022", "E2024"])
