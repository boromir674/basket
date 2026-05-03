#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanity-check games_manifest.json against stored multi-game bundles."
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing games_manifest.json and multi_drilldown_real_data_E*_*.json (default: data)",
    )
    parser.add_argument(
        "--manifest",
        default="games_manifest.json",
        help="Manifest filename inside --data-dir (default: games_manifest.json)",
    )
    parser.add_argument(
        "--show-missing-sample",
        type=int,
        default=10,
        help="How many missing file examples to print (default: 10)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    manifest_path = data_dir / args.manifest

    if not data_dir.exists():
        print(f"ERROR: data dir not found: {data_dir}")
        return 2
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}")
        return 2

    try:
        payload = _load_json(manifest_path)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot parse manifest JSON: {manifest_path}: {exc}")
        return 2

    if not isinstance(payload, list):
        print(f"ERROR: manifest root is not a list: {manifest_path}")
        return 2

    rows: list[dict[str, Any]] = [r for r in payload if isinstance(r, dict)]
    non_dict_rows = len(payload) - len(rows)

    season_counts = Counter()
    missing_files: list[str] = []
    missing_required: list[str] = []

    by_file = Counter()
    by_season_game = Counter()

    for idx, row in enumerate(rows):
        file_name = str(row.get("file") or "")
        seasoncode = str(row.get("seasoncode") or "")
        gamecode = row.get("gamecode")

        if seasoncode:
            season_counts[seasoncode] += 1

        if not file_name:
            missing_required.append(f"row[{idx}] missing file")
        if not seasoncode:
            missing_required.append(f"row[{idx}] missing seasoncode")
        if gamecode is None:
            missing_required.append(f"row[{idx}] missing gamecode")

        if file_name:
            by_file[file_name] += 1
            path = data_dir / file_name
            if not path.exists():
                missing_files.append(file_name)

        if seasoncode and gamecode is not None:
            by_season_game[(seasoncode, str(gamecode))] += 1

    duplicate_files = sorted([name for name, c in by_file.items() if c > 1])
    duplicate_season_games = sorted([k for k, c in by_season_game.items() if c > 1])

    stored_files = {p.name for p in data_dir.glob("multi_drilldown_real_data_E*_*.json")}
    listed_files = {name for name in by_file.keys() if name}
    orphan_files = sorted(stored_files - listed_files)

    print("=== Manifest Sanity Check ===")
    print(f"data_dir: {data_dir}")
    print(f"manifest: {manifest_path.name}")
    print(f"manifest_rows_total: {len(payload)}")
    print(f"manifest_rows_dict: {len(rows)}")
    print(f"manifest_rows_non_dict: {non_dict_rows}")
    print(f"seasons_in_manifest: {len(season_counts)}")

    if season_counts:
        print("season_distribution:")
        for sc in sorted(season_counts.keys()):
            print(f"  {sc}: {season_counts[sc]}")

    print(f"missing_required_fields: {len(missing_required)}")
    print(f"missing_referenced_files: {len(missing_files)}")
    print(f"duplicate_file_rows: {len(duplicate_files)}")
    print(f"duplicate_season_game_rows: {len(duplicate_season_games)}")
    print(f"orphan_multi_files_not_listed: {len(orphan_files)}")

    if missing_required:
        print("missing_required_fields_sample:")
        for msg in missing_required[: args.show_missing_sample]:
            print(f"  - {msg}")

    if missing_files:
        print("missing_referenced_files_sample:")
        for name in missing_files[: args.show_missing_sample]:
            print(f"  - {name}")

    if duplicate_files:
        print("duplicate_file_rows_sample:")
        for name in duplicate_files[: args.show_missing_sample]:
            print(f"  - {name}")

    if duplicate_season_games:
        print("duplicate_season_game_rows_sample:")
        for sc, gc in duplicate_season_games[: args.show_missing_sample]:
            print(f"  - {sc}/{gc}")

    if orphan_files:
        print("orphan_multi_files_not_listed_sample:")
        for name in orphan_files[: args.show_missing_sample]:
            print(f"  - {name}")

    has_errors = any(
        [
            non_dict_rows > 0,
            len(missing_required) > 0,
            len(missing_files) > 0,
            len(duplicate_files) > 0,
            len(duplicate_season_games) > 0,
        ]
    )

    if has_errors:
        print("RESULT: FAIL")
        return 1

    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
