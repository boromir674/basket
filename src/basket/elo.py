"""ELO rating engine (shared library).

This module contains the Elo math + season/game aggregation logic.
It is intentionally dependency-free so it can be reused by:
- the CLI wrapper in `elo.py`
- Docker entrypoints
- pytest unit tests

Keep this module as the single source of truth for Elo computations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

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
# Season-level helpers
# ---------------------------------------------------------------------------

def _parse_gamedate(gamedate: Optional[str]) -> str:
    """Return a sortable date string (first 10 chars of the ISO date)."""
    if not gamedate:
        return ""
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
        return 0.5
    return None


# ---------------------------------------------------------------------------
# Core computation (in-memory)
# ---------------------------------------------------------------------------

def compute_elo_from_games(
    games: Iterable[dict[str, Any]],
    *,
    k_factor: float = DEFAULT_K,
    initial_rating: float = DEFAULT_INITIAL,
    sort_games: bool = True,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Compute Elo ratings + history from an iterable of game dicts.

    Expected game keys (minimal):
      - team_a, team_b
      - winner (optional)
      - score_a, score_b (optional)
      - gamedate (optional)
      - gamecode (optional)

    Returns:
      - ratings: mapping team -> elo
      - history: list of per-game entries (includes before/after ratings)
    """

    games_list = list(games)
    if sort_games:
        games_list.sort(
            key=lambda g: (
                _parse_gamedate(g.get("gamedate")),
                int(g.get("gamecode") or 0),
            )
        )

    ratings: dict[str, float] = {}
    history: list[dict[str, Any]] = []

    for game in games_list:
        team_a = game.get("team_a")
        team_b = game.get("team_b")
        if not team_a or not team_b:
            continue

        ratings.setdefault(team_a, initial_rating)
        ratings.setdefault(team_b, initial_rating)
        elo_a = ratings.get(team_a, initial_rating)
        elo_b = ratings.get(team_b, initial_rating)

        outcome = _outcome_score(
            game.get("winner"),
            team_a,
            team_b,
            game.get("score_a"),
            game.get("score_b"),
        )

        gamecode = game.get("gamecode")
        gamedate = game.get("gamedate")
        score_a = game.get("score_a")
        score_b = game.get("score_b")
        winner = game.get("winner")

        if outcome is None:
            history.append(
                {
                    "gamecode": gamecode,
                    "gamedate": gamedate,
                    "team_a": team_a,
                    "team_b": team_b,
                    "score_a": score_a,
                    "score_b": score_b,
                    "winner": winner,
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
                "gamecode": gamecode,
                "gamedate": gamedate,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
                "elo_a_before": elo_a,
                "elo_b_before": elo_b,
                "elo_a_after": new_a,
                "elo_b_after": new_b,
            }
        )

    return ratings, history


# ---------------------------------------------------------------------------
# File-system integration (existing behavior)
# ---------------------------------------------------------------------------

def compute_elo_for_season(
    output_dir: Path,
    seasoncode: str,
    k_factor: float = DEFAULT_K,
    initial_rating: float = DEFAULT_INITIAL,
) -> dict[str, Any]:
    """Compute Elo ratings for all games in `output_dir` for `seasoncode`.

    This preserves the previous CLI behavior:
      - scan for `multi_drilldown_real_data_{seasoncode}_*.json`
      - process chronologically
      - write `elo_{seasoncode}.json`
    """

    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    game_files = list(output_dir.glob(pattern))

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

    ratings, history = compute_elo_from_games(
        games,
        k_factor=k_factor,
        initial_rating=initial_rating,
        sort_games=True,
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
