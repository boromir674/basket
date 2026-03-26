from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

from build_from_euroleague_api import run_game


def parse_gamecodes(raw_values: List[str]) -> List[int]:
    """Parse one or more gamecode values, allowing comma-separated input.

    Examples:
    --gamecode 54 --gamecode 55
    --gamecode 54,55,56
    """
    gamecodes: List[int] = []
    for raw in raw_values:
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                gamecodes.append(int(part))
            except ValueError:
                raise SystemExit(f"Invalid gamecode value: {part!r}")
    if not gamecodes:
        raise SystemExit("At least one --gamecode is required")
    return gamecodes


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run Euroleague Sankey pipeline for one or more games.")
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2021")
    parser.add_argument(
        "--gamecode",
        action="append",
        required=True,
        help="Game code(s). Can be repeated or comma-separated (e.g. 54 or 54,55)",
    )
    parser.add_argument(
        "--output-pattern",
        default="multi_drilldown_real_data_{seasoncode}_{gamecode}.json",
        help=(
            "Output filename pattern. Format variables: {seasoncode}, {gamecode}. "
            "Default: multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
        help="Directory to save processed output files. Defaults to BASKET_APP_FILE_STORE_URI/processed.",
    )
    args = parser.parse_args(argv)

    seasoncode: str = args.seasoncode
    gamecodes = parse_gamecodes(args.gamecode)

    # Ensure the output directory exists
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Running pipeline for games:")
    for gc in gamecodes:
        out_name = args.output_pattern.format(seasoncode=seasoncode, gamecode=gc)
        out_path = output_dir / out_name
        print(f"  - {seasoncode} / {gc} -> {out_path}")
        payload = run_game(seasoncode, gc, str(out_path))

        # Lightweight feedback loop: echo a compact per-game summary.
        meta = payload.get("meta", {})
        views = payload.get("views", {})
        top = views.get("top", {})
        starts = top.get("starts", {})
        print(
            "    Summary:",
            f"teams=({meta.get('team_a')} vs {meta.get('team_b')}),",
            f"starts={starts}",
        )

    print("All requested games processed.")


if __name__ == "__main__":
    main()
