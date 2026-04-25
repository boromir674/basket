from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from basket.clubs import DEFAULT_REGISTRY, canonicalize_json
from build_from_euroleague_api import extract_points_rows, normalize_game_date


@dataclass(frozen=True)
class SeasonReport:
    seasoncode: str
    games: int
    distinct_teams: int
    teams: list[str]
    earliest: str | None = None
    latest: str | None = None


def iter_season_game_files(data_dir: Path, seasoncode: str) -> Iterable[Path]:
    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    yield from sorted(data_dir.glob(pattern))


def find_unknown_club_names(
    *,
    data_dir: Path,
    seasoncodes: Iterable[str] | None = None,
) -> list[str]:
    """Return club names found in stored data but missing from runtime registry.

    Discovery is based on `meta.team_a` / `meta.team_b` fields in processed files.
    """

    known_names = set(DEFAULT_REGISTRY.alias_to_canonical.keys())
    unknown: set[str] = set()

    if seasoncodes is None:
        files = sorted(data_dir.glob("multi_drilldown_real_data_*_*.json"))
    else:
        files = []
        for seasoncode in seasoncodes:
            files.extend(iter_season_game_files(data_dir, seasoncode))

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        if not isinstance(payload, dict):
            continue
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            continue

        for key in ("team_a", "team_b"):
            raw = meta.get(key)
            if not isinstance(raw, str):
                continue
            name = raw.strip()
            if not name:
                continue
            if name not in known_names:
                unknown.add(name)

    return sorted(unknown)


def _extract_gamedate_from_raw_points(points_payload: Any) -> str | None:
    dates: list[str] = []
    for row in extract_points_rows(points_payload):
        if not isinstance(row, dict):
            continue
        normalized = normalize_game_date(row.get("UTC"))
        if normalized:
            dates.append(normalized)
    if not dates:
        return None
    return min(dates)


def _canonicalize_payload(payload: Any) -> Any:
    return canonicalize_json(payload, registry=DEFAULT_REGISTRY)


def normalize_season_data_files(
    *,
    seasoncode: str,
    data_dir: Path,
    dry_run: bool = False,
    workers: int = 1,
) -> dict[str, Any]:
    """Rewrite season JSON files in-place to canonical team names.

    Returns counts:
      - files_total
      - files_changed
    """

    files = list(iter_season_game_files(data_dir, seasoncode))
    changed = 0
    normalized_aliases: set[str] = set()
    normalized_canonical: set[str] = set()

    max_workers = max(1, int(workers))

    def _process_file(path: Path) -> tuple[bool, set[str], set[str]]:
        """Process one file and return (changed, aliases, canonical)."""
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            return False, set(), set()

        aliases: set[str] = set()
        canonical: set[str] = set()

        # Track successful team-name normalizations from meta.team_a/team_b.
        if isinstance(payload, dict):
            meta = payload.get("meta")
            if isinstance(meta, dict):
                for k in ("team_a", "team_b"):
                    raw_name = meta.get(k)
                    if not isinstance(raw_name, str):
                        continue
                    raw_name = raw_name.strip()
                    if not raw_name:
                        continue
                    normalized = DEFAULT_REGISTRY.normalize_team_name(raw_name)
                    if normalized != raw_name:
                        aliases.add(raw_name)
                        canonical.add(normalized)

        new_payload = _canonicalize_payload(payload)
        file_changed = new_payload != payload
        if file_changed and not dry_run:
            new_raw = json.dumps(new_payload, ensure_ascii=False, indent=2)
            path.write_text(new_raw + "\n", encoding="utf-8")
        return file_changed, aliases, canonical

    if max_workers == 1:
        results = [_process_file(path) for path in files]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_process_file, files))

    for file_changed, aliases, canonical in results:
        if file_changed:
            changed += 1
        normalized_aliases.update(aliases)
        normalized_canonical.update(canonical)

    return {
        "files_total": len(files),
        "files_changed": changed,
        "normalized_aliases": sorted(normalized_aliases),
        "normalized_canonical": sorted(normalized_canonical),
    }


def build_season_report(*, seasoncode: str, data_dir: Path) -> SeasonReport:
    files = list(iter_season_game_files(data_dir, seasoncode))
    teams: set[str] = set()
    dates: list[str] = []

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

        gd = meta.get("gamedate")
        if isinstance(gd, str) and gd.strip():
            dates.append(gd.strip())

    ordered = sorted(teams)
    return SeasonReport(
        seasoncode=seasoncode,
        games=len(files),
        distinct_teams=len(teams),
        teams=ordered,
        earliest=min(dates) if dates else None,
        latest=max(dates) if dates else None,
    )


def backfill_season_gamedates(
    *,
    seasoncode: str,
    data_dir: Path,
    raw_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill meta.gamedate in processed game bundles using saved raw Points payloads."""

    files = list(iter_season_game_files(data_dir, seasoncode))
    changed = 0
    missing_raw = 0
    missing_date = 0

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            continue

        gamecode = meta.get("gamecode")
        try:
            gamecode_int = int(gamecode)
        except Exception:  # noqa: BLE001
            continue

        raw_points_path = raw_dir / f"raw_pts_{seasoncode}_{gamecode_int}.json"
        if not raw_points_path.exists():
            missing_raw += 1
            continue

        try:
            raw_points = json.loads(raw_points_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            missing_raw += 1
            continue

        gamedate = _extract_gamedate_from_raw_points(raw_points)
        if not gamedate:
            missing_date += 1
            continue

        if meta.get("gamedate") == gamedate:
            continue

        changed += 1
        if not dry_run:
            meta["gamedate"] = gamedate
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "files_total": len(files),
        "files_changed": changed,
        "missing_raw": missing_raw,
        "missing_date": missing_date,
    }
