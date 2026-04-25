from __future__ import annotations

import json
from pathlib import Path

import pytest

import build_from_euroleague_api as pipeline


def test_run_game_stores_gamedate_from_mocked_points_utc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN one mocked game whose points feed exposes per-play UTC timestamps.
    pbp_json = {
        "TeamA": "Team Alpha",
        "TeamB": "Team Beta",
        "FirstQuarter": [
            {
                "NUMBEROFPLAY": 1,
                "PLAYTYPE": "2FGM",
                "TEAM": "Team Alpha",
                "PLAYER_ID": "P1",
                "PLAYER": "PLAYER ONE",
            }
        ],
    }
    points_json = {
        "Rows": [
            {
                "NumberOfPlay": 1,
                "UTC": "20251003194512",
                "CoordX": 0,
                "Zone": "paint",
            }
        ]
    }
    box_json = {
        "Stats": [
            {
                "Team": "Team Alpha",
                "PlayersStats": [{"Player_ID": "P1", "Player": "PLAYER ONE", "Points": 2}],
            },
            {
                "Team": "Team Beta",
                "PlayersStats": [],
            },
        ]
    }

    monkeypatch.setattr(pipeline, "fetch_sources", lambda seasoncode, gamecode: (pbp_json, points_json, box_json))

    output_path = tmp_path / "mocked_game.json"

    # WHEN the pipeline runs for that mocked game.
    payload = pipeline.run_game("E2025", 1, str(output_path))
    stored_payload = json.loads(output_path.read_text(encoding="utf-8"))

    # THEN the payload and stored file should both carry the game date.
    assert payload["meta"]["gamedate"] == "2025-10-03"
    assert stored_payload["meta"]["gamedate"] == "2025-10-03"


@pytest.mark.parametrize("seasoncode, gamecode", [("E2021", 54)])
def test_run_game_fetches_and_persists_real_api_gamedate(
    tmp_path: Path,
    seasoncode: str,
    gamecode: int,
) -> None:
    # GIVEN one real Euroleague API game.
    output_path = tmp_path / f"{seasoncode}_{gamecode}.json"

    # WHEN the live pipeline fetches and stores that game.
    payload = pipeline.run_game(seasoncode, gamecode, str(output_path))
    stored_payload = json.loads(output_path.read_text(encoding="utf-8"))

    # THEN the resulting payload and persisted file should both include a non-empty game date.
    assert payload["meta"]["gamedate"]
    assert stored_payload["meta"]["gamedate"]
    assert payload["meta"]["gamedate"] == stored_payload["meta"]["gamedate"]
