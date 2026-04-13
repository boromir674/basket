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
import json
import os
from pathlib import Path
from typing import Any, Optional


DEFAULT_K = 32
DEFAULT_INITIAL = 1500


# ---------------------------------------------------------------------------
# Pure ELO math
# ---------------------------------------------------------------------------

def expected_score(rating_a: float, rating_b: float) -> float:
    """Return the expected win probability for team A (0-1)."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_ratings(
    rating_a: float,
    rating_b: float,
    score_a: float,
    k: float = DEFAULT_K,
) -> tuple[float, float]:
    """Update ratings after one game.

    Args:
        rating_a: Pre-game ELO for team A.
        rating_b: Pre-game ELO for team B.
        score_a: Actual score for team A (1 = win, 0 = loss, 0.5 = draw).
        k: K-factor controlling rating volatility.

    Returns:
        (new_rating_a, new_rating_b)
    """
    ea = expected_score(rating_a, rating_b)
    new_a = rating_a + k * (score_a - ea)
    new_b = rating_b + k * ((1.0 - score_a) - (1.0 - ea))
    return round(new_a, 2), round(new_b, 2)


# ---------------------------------------------------------------------------
# Season-level computation
# ---------------------------------------------------------------------------

def _parse_gamedate(gamedate: Optional[str]) -> str:
    """Return a sortable date string, defaulting to empty string so games
    without a date sort to the front (will be processed first)."""
    if not gamedate:
        return ""
    # API returns ISO strings or "YYYY-MM-DD" fragments – take first 10 chars.
    return str(gamedate)[:10]


def _outcome_score(
    winner: Optional[str],
    team_a: str,
    team_b: str,
    score_a: Optional[int],
    score_b: Optional[int],
) -> Optional[float]:
    """Return the ELO score for team A (1 win, 0 loss, 0.5 draw / unknown).

    Returns None if we cannot determine the outcome.
    """
    if winner == team_a:
        return 1.0
    if winner == team_b:
        return 0.0
    if winner is None and score_a is not None and score_b is not None:
        if score_a > score_b:
            return 1.0
        if score_b > score_a:
            return 0.0
        return 0.5  # genuine draw
    return None


def compute_elo_for_season(
    output_dir: Path,
    seasoncode: str,
    k_factor: float = DEFAULT_K,
    initial_rating: float = DEFAULT_INITIAL,
) -> dict[str, Any]:
    """Compute ELO ratings for all games in ``output_dir`` for ``seasoncode``.

    Returns the full ELO payload dict (also written to disk).
    """
    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    game_files = list(output_dir.glob(pattern))

    # Load metadata only (avoid expensive full-parse)
    games: list[dict[str, Any]] = []
    for path in game_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            continue
        try:
            gamecode = int(meta.get("gamecode", 0))
        except (ValueError, TypeError):
            continue
        games.append(
            {
                "gamecode": gamecode,
                "gamedate": meta.get("gamedate"),
                "team_a": meta.get("team_a"),
                "team_b": meta.get("team_b"),
                "score_a": meta.get("score_a"),
                "score_b": meta.get("score_b"),
                "winner": meta.get("winner"),
            }
        )

    # Sort chronologically (by gamedate ascending, then by gamecode as tie-break)
    games.sort(key=lambda g: (_parse_gamedate(g["gamedate"]), g["gamecode"]))

    ratings: dict[str, float] = {}
    history: list[dict[str, Any]] = []

    for game in games:
        team_a = game["team_a"]
        team_b = game["team_b"]
        if not team_a or not team_b:
            continue

        elo_a = ratings.get(team_a, initial_rating)
        elo_b = ratings.get(team_b, initial_rating)

        outcome = _outcome_score(
            game["winner"], team_a, team_b, game["score_a"], game["score_b"]
        )
        if outcome is None:
            # Cannot determine winner – record but do not update ratings
            history.append(
                {
                    "gamecode": game["gamecode"],
                    "gamedate": game["gamedate"],
                    "team_a": team_a,
                    "team_b": team_b,
                    "score_a": game["score_a"],
                    "score_b": game["score_b"],
                    "winner": game["winner"],
                    "elo_a_before": elo_a,
                    "elo_b_before": elo_b,
                    "elo_a_after": elo_a,
                    "elo_b_after": elo_b,
                    "outcome_unknown": True,
                }
            )
            continue

        new_a, new_b = update_ratings(elo_a, elo_b, outcome, k_factor)
        ratings[team_a] = new_a
        ratings[team_b] = new_b

        history.append(
            {
                "gamecode": game["gamecode"],
                "gamedate": game["gamedate"],
                "team_a": team_a,
                "team_b": team_b,
                "score_a": game["score_a"],
                "score_b": game["score_b"],
                "winner": game["winner"],
                "elo_a_before": elo_a,
                "elo_b_before": elo_b,
                "elo_a_after": new_a,
                "elo_b_after": new_b,
            }
        )

    payload: dict[str, Any] = {
        "seasoncode": seasoncode,
        "k_factor": k_factor,
        "initial_rating": initial_rating,
        "ratings": ratings,
        "history": history,
    }

    out_path = output_dir / f"elo_{seasoncode}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote ELO file with {len(history)} games -> {out_path}")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute ELO ratings for a Euroleague season."
    )
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2024")
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
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).resolve()
    if not output_dir.exists():
        print(f"Output directory does not exist: {output_dir}")
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
