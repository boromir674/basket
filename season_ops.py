from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from basket.clubs import DEFAULT_REGISTRY, canonicalize_json


@dataclass(frozen=True)
class SeasonReport:
    seasoncode: str
    games: int
    distinct_teams: int
    teams: list[str]
def iter_season_game_files(data_dir: Path, seasoncode: str) -> Iterable[Path]:
    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    yield from sorted(data_dir.glob(pattern))


def _canonicalize_payload(payload: Any) -> Any:
    return canonicalize_json(payload, registry=DEFAULT_REGISTRY)


def normalize_season_data_files(
    *,
    seasoncode: str,
    data_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Rewrite season JSON files in-place to canonical team names.

    Returns counts:
      - files_total
      - files_changed
    """

    files = list(iter_season_game_files(data_dir, seasoncode))
    changed = 0

    for path in files:
        raw = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue

        new_payload = _canonicalize_payload(payload)

        if new_payload != payload:
            changed += 1
            if not dry_run:
                new_raw = json.dumps(new_payload, ensure_ascii=False, indent=2)
                path.write_text(new_raw + "\n", encoding="utf-8")

    return {"files_total": len(files), "files_changed": changed}


def build_season_report(*, seasoncode: str, data_dir: Path) -> SeasonReport:
    files = list(iter_season_game_files(data_dir, seasoncode))
    teams: set[str] = set()

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        team_a = meta.get("team_a")
        team_b = meta.get("team_b")

        if isinstance(team_a, str) and team_a.strip():
            teams.add(team_a.strip())
        if isinstance(team_b, str) and team_b.strip():
            teams.add(team_b.strip())

    ordered = sorted(teams)
    return SeasonReport(
        seasoncode=seasoncode,
        games=len(files),
        distinct_teams=len(teams),
        teams=ordered,
    )
