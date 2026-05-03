from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import List

from build_from_euroleague_api import run_game
from validate_output import validate_file


def find_missing(seasoncode: str, start: int, end: int, output_dir: Path) -> List[int]:
    missing: List[int] = []
    for gamecode in range(start, end + 1):
        out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name
        if not out_path.exists():
            missing.append(gamecode)
            continue
        # exists -> check semantic validity
        try:
            ok, _ = validate_file(out_path)
            if not ok:
                missing.append(gamecode)
        except Exception:
            missing.append(gamecode)
    return missing


def retry_games(seasoncode: str, gamecodes: List[int], output_dir: Path, attempts: int, backoff: int, dry_run: bool) -> int:
    """Retry the supplied gamecodes.

    Use a fixed small backoff between attempts (no exponential growth).
    """
    successes = 0
    failures = 0
    for gamecode in gamecodes:
        out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name
        print(f"[RETRY] {seasoncode}/{gamecode} -> {out_path}")
        if dry_run:
            print("  [DRY-RUN] would attempt to fetch")
            continue

        for attempt in range(1, attempts + 1):
            try:
                run_game(seasoncode, gamecode, str(out_path))
            except Exception as exc:
                print(f"  [ERROR] attempt={attempt} -> {exc}")
                if attempt < attempts:
                    sleep_time = backoff
                    print(f"  [BACKOFF] sleeping {sleep_time}s before retry (fixed)")
                    time.sleep(sleep_time)
                continue

            try:
                ok, msg = validate_file(out_path)
            except Exception as exc:
                ok = False
                msg = f"validate-exception: {exc}"

            if ok:
                print(f"  [OK] {msg}")
                successes += 1
                break
            else:
                print(f"  [FAIL] {msg}")
                if attempt < attempts:
                    sleep_time = backoff
                    print(f"  [BACKOFF] sleeping {sleep_time}s before retry (fixed)")
                    time.sleep(sleep_time)
                else:
                    failures += 1

    return successes, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry missing or invalid processed JSONs for a season.")
    parser.add_argument("--seasoncode", required=True)
    parser.add_argument("--start-gamecode", type=int, default=1)
    parser.add_argument("--end-gamecode", type=int, default=200)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--attempts", type=int, default=3, help="Attempts per missing game")
    parser.add_argument("--backoff", type=int, default=5, help="Base backoff seconds (multiplied by attempt)")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning for missing/invalid games for {args.seasoncode} {args.start_gamecode}..{args.end_gamecode} in {output_dir}")
    missing = find_missing(args.seasoncode, args.start_gamecode, args.end_gamecode, output_dir)
    print(f"Found {len(missing)} missing/invalid games")
    if not missing:
        print("Nothing to do.")
        return

    successes, failures = retry_games(args.seasoncode, missing, output_dir, args.attempts, args.backoff, args.dry_run)

    print(f"Retry summary: successes={successes}, failures={failures}")

    print(f"manifest_not_rebuilt=1 (decoupled) | run: rebuild_manifest --all-seasons --output-dir {output_dir}")


if __name__ == "__main__":
    main()
