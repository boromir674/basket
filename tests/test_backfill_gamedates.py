from __future__ import annotations

import json
from pathlib import Path

from season_ops import backfill_season_gamedates


def test_backfill_season_gamedates_updates_existing_processed_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    raw_dir = tmp_path / "assets"
    data_dir.mkdir()
    raw_dir.mkdir()

    processed_path = data_dir / "multi_drilldown_real_data_E2025_7.json"
    processed_path.write_text(
        json.dumps(
            {
                "meta": {
                    "seasoncode": "E2025",
                    "gamecode": 7,
                    "team_a": "Alpha",
                    "team_b": "Beta",
                    "gamedate": None,
                },
                "views": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    raw_points_path = raw_dir / "raw_pts_E2025_7.json"
    raw_points_path.write_text(
        json.dumps(
            {
                "Rows": [
                    {"UTC": "20251007201544", "NumberOfPlay": 1},
                    {"UTC": "20251007211644", "NumberOfPlay": 2},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    counts = backfill_season_gamedates(seasoncode="E2025", data_dir=data_dir, raw_dir=raw_dir, dry_run=False)
    updated = json.loads(processed_path.read_text(encoding="utf-8"))

    assert counts == {
        "files_total": 1,
        "files_changed": 1,
        "missing_raw": 0,
        "missing_date": 0,
    }
    assert updated["meta"]["gamedate"] == "2025-10-07"
