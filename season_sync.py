from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any

from build_from_euroleague_api import run_game
from validate_output import validate_file


def build_manifest(output_dir: Path, seasoncode: str) -> None:
    """Scan JSON files and write a simple manifest for the UI.

    Manifest shape:
    [{"file": "multi_drilldown_real_data_E2021_54.json",
      "seasoncode": "E2021",
      "gamecode": 54,
      "team_a": "...",
      "team_b": "..."}, ...]
    """
    entries: List[Dict[str, Any]] = []

    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    for path in sorted(output_dir.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {})
        try:
            gamecode = int(meta.get("gamecode"))
        except Exception:  # noqa: BLE001
            continue
        entries.append(
            {
                "file": path.name,
                "seasoncode": seasoncode,
                "gamecode": gamecode,
                "team_a": meta.get("team_a"),
                "team_b": meta.get("team_b"),
                "gamedate": meta.get("gamedate"),
                "synced_at": meta.get("synced_at"),
            }
        )

    manifest_path = output_dir / "games_manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"Wrote manifest with {len(entries)} entries -> {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync a block of games for a season.")
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2024")
    parser.add_argument("--start-gamecode", type=int, default=1, help="First gamecode to try (inclusive)")
    parser.add_argument("--end-gamecode", type=int, default=200, help="Last gamecode to try (inclusive)")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where JSON files will be written (default: current directory)",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=25,
        help="Stop early after this many failures (e.g. missing games)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild games even if output JSON already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write or validate JSON, just log what would be done",
    )

    args = parser.parse_args()

    seasoncode: str = args.seasoncode
    start_gc: int = args.start_gamecode
    end_gc: int = args.end_gamecode
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== Season sync for {seasoncode}: {start_gc}..{end_gc} (mode={mode}) ===")

    failures = 0
    processed = 0

    for gamecode in range(start_gc, end_gc + 1):
        out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name

        if out_path.exists() and not args.force:
            print(f"[SKIP existing] {seasoncode}/{gamecode} -> {out_path}")
            continue

        if args.dry_run:
            print(f"[DRY-RUN] would build {seasoncode}/{gamecode} -> {out_path}")
            processed += 1
            continue

        print(f"[RUN] {seasoncode}/{gamecode} -> {out_path}")
        try:
            run_game(seasoncode, gamecode, str(out_path))
        except SystemExit as exc:
            print(f"  [ERROR] pipeline exited: {exc}")
            failures += 1
            if failures >= args.max_failures:
                print("Too many failures, stopping early.")
                break
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] unexpected: {exc}")
            failures += 1
            if failures >= args.max_failures:
                print("Too many failures, stopping early.")
                break
            continue

        is_valid, message = validate_file(out_path)
        status = "OK" if is_valid else "FAIL"
        print(f"  [VALIDATION {status}] {message}")
        if not is_valid:
            failures += 1
            if failures >= args.max_failures:
                print("Too many failures, stopping early.")
                break

        processed += 1

    print(f"=== Done. processed={processed}, failures={failures} (mode={mode}) ===")

    if not args.dry_run:
        # Refresh manifest for this season so the UI can list all games.
        build_manifest(output_dir, seasoncode)


if __name__ == "__main__":
    main()
