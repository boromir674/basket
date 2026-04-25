"""ELO rating engine for Basket platform.

Usage (standalone CLI):
    python elo.py --seasoncode E2024 [--output-dir assets/processed]
                  [--k-factor 32] [--initial-rating 1500]

The script:
1. Scans ``output_dir`` for ``multi_drilldown_real_data_{seasoncode}_*.json``
2. Reads ``meta.gamedate``, ``meta.team_a``, ``meta.team_b``, ``meta.winner``
   (and ``meta.score_a`` / ``meta.score_b`` as a tie-break / fallback)
3. Processes games chronologically and updates ELO ratings after each game
4. Writes ``elo_{seasoncode}.json`` to ``output_dir``

Output format:
{
  "seasoncode": "E2024",
  "k_factor": 32,
  "initial_rating": 1500,
  "ratings": {"Real Madrid": 1563, "Fenerbahce": 1601, ...},
  "history": [
    {
      "gamecode": 47,
      "gamedate": "2024-03-15",
      "team_a": "Real Madrid",
      "team_b": "Panathinaikos",
      "score_a": 85,
      "score_b": 78,
      "winner": "Real Madrid",
      "elo_a_before": 1550,
      "elo_b_before": 1500,
      "elo_a_after": 1563,
      "elo_b_after": 1488
    },
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from basket.elo import (
    DEFAULT_INITIAL,
    DEFAULT_K,
    compute_elo_for_season,
    compute_elo_for_seasoncodes,
    recompute_multiseason_elo_if_needed,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute ELO ratings for a Euroleague season."
    )
    parser.add_argument("--seasoncode", required=False, help="Season code, e.g. E2024")
    parser.add_argument(
        "--seasoncodes",
        default="",
        help="Comma-separated seasoncodes for multi-season Elo (example: E2022,E2023,E2024)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
        help="Directory containing game JSON files (default: assets/processed)",
    )
    parser.add_argument(
        "--k-factor",
        type=float,
        default=DEFAULT_K,
        help=f"ELO K-factor (default: {DEFAULT_K})",
    )
    parser.add_argument(
        "--initial-rating",
        type=float,
        default=DEFAULT_INITIAL,
        help=f"Starting ELO for teams with no history (default: {DEFAULT_INITIAL})",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-discover stored seasons and recompute elo_multiseason.json only when stale/missing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recomputation in --auto mode even when elo_multiseason.json looks up-to-date",
    )
    parser.add_argument(
        "--output-name",
        default="elo_multiseason.json",
        help="Output filename used for multi-season payloads (default: elo_multiseason.json)",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).resolve()
    if not output_dir.exists():
        print(f"Output directory does not exist: {output_dir}")
        return 1

    if args.auto:
        recomputed, _payload, reason = recompute_multiseason_elo_if_needed(
            output_dir=output_dir,
            k_factor=args.k_factor,
            initial_rating=args.initial_rating,
            force=args.force,
            output_name=args.output_name,
        )
        if recomputed:
            print(f"Auto recompute complete ({args.output_name})")
        else:
            print(f"Auto recompute skipped: {reason}")
        return 0

    seasoncodes = [s.strip() for s in str(args.seasoncodes).split(",") if s.strip()]
    if seasoncodes:
        compute_elo_for_seasoncodes(
            output_dir=output_dir,
            seasoncodes=seasoncodes,
            k_factor=args.k_factor,
            initial_rating=args.initial_rating,
            output_name=args.output_name,
        )
        return 0

    if not args.seasoncode:
        print("--seasoncode is required unless --seasoncodes or --auto is provided")
        return 1

    compute_elo_for_season(
        output_dir=output_dir,
        seasoncode=args.seasoncode,
        k_factor=args.k_factor,
        initial_rating=args.initial_rating,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
