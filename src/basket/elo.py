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
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from basket.clubs import DEFAULT_REGISTRY

DEFAULT_K = 32
DEFAULT_INITIAL = 1500
SEASONCODE_RE = re.compile(r"^E(\d{4})$")


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


def _seasoncode_year(seasoncode: str) -> Optional[int]:
    """Return the integer start year for seasoncodes like E2025."""
    m = SEASONCODE_RE.match(str(seasoncode or "").strip())
    if not m:
        return None
    return int(m.group(1))


def season_label_from_code(seasoncode: str) -> str:
    """Format E2025 -> 2025-2026, fallback to the raw seasoncode."""
    y = _seasoncode_year(seasoncode)
    if y is None:
        return str(seasoncode)
    return f"{y}-{y + 1}"


def are_consecutive_seasoncodes(seasoncodes: Iterable[str]) -> bool:
    """Return True when seasoncodes form a year-by-year consecutive block."""
    years = [_seasoncode_year(s) for s in seasoncodes]
    if not years or any(y is None for y in years):
        return False
    ys = sorted({int(y) for y in years if y is not None})
    return all((ys[i + 1] - ys[i]) == 1 for i in range(len(ys) - 1))


def discover_stored_seasoncodes(output_dir: Path) -> list[str]:
    """Discover seasoncodes from stored game bundles in output_dir."""

    return sorted(
        {
            str(p.stem.split("_")[4])
            for p in output_dir.glob("multi_drilldown_real_data_E*_*.json")
            if len(p.stem.split("_")) >= 6 and _seasoncode_year(p.stem.split("_")[4]) is not None
        },
        key=lambda s: _seasoncode_year(s) or 0
    )


def missing_seasoncodes_in_range(seasoncodes: Iterable[str]) -> list[str]:
    """Return any missing seasoncodes between the first and last year."""
    years = sorted({_seasoncode_year(s) for s in seasoncodes if _seasoncode_year(s) is not None})
    if not years:
        return []
    missing: list[str] = []
    for y in range(years[0], years[-1] + 1):
        code = f"E{y}"
        if y not in years:
            missing.append(code)
    return missing


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


def _canonicalize_game_teams(
    team_a: Any,
    team_b: Any,
    winner: Any,
) -> tuple[str | None, str | None, str | None]:
    """Normalize team labels so Elo aggregates per canonical club identity."""
    a = DEFAULT_REGISTRY.normalize_team_name(team_a) if team_a else None
    b = DEFAULT_REGISTRY.normalize_team_name(team_b) if team_b else None
    w = DEFAULT_REGISTRY.normalize_team_name(winner) if winner else None
    return a, b, w


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
        seasoncode = game.get("seasoncode")
        season_label = game.get("season_label")
        score_a = game.get("score_a")
        score_b = game.get("score_b")
        winner = game.get("winner")

        if outcome is None:
            history.append(
                {
                    "gamecode": gamecode,
                    "gamedate": gamedate,
                    "seasoncode": seasoncode,
                    "season_label": season_label,
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
                "seasoncode": seasoncode,
                "season_label": season_label,
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
        team_a, team_b, winner = _canonicalize_game_teams(
            meta.get("team_a"),
            meta.get("team_b"),
            meta.get("winner"),
        )
        games.append(
            {
                "gamecode": gamecode,
                "gamedate": meta.get("gamedate"),
                "team_a": team_a,
                "team_b": team_b,
                "score_a": meta.get("score_a"),
                "score_b": meta.get("score_b"),
                "winner": winner,
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


def _collect_games_for_seasoncodes(output_dir: Path, seasoncodes: Iterable[str]) -> list[dict[str, Any]]:
    """Load game metadata for one or more seasoncodes from output_dir."""
    games: list[dict[str, Any]] = []
    for seasoncode in seasoncodes:
        pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
        for path in output_dir.glob(pattern):
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
            team_a, team_b, winner = _canonicalize_game_teams(
                meta.get("team_a"),
                meta.get("team_b"),
                meta.get("winner"),
            )
            games.append(
                {
                    "seasoncode": seasoncode,
                    "season_label": season_label_from_code(seasoncode),
                    "gamecode": gamecode,
                    "gamedate": meta.get("gamedate"),
                    "team_a": team_a,
                    "team_b": team_b,
                    "score_a": meta.get("score_a"),
                    "score_b": meta.get("score_b"),
                    "winner": winner,
                }
            )
    return games


def compute_elo_for_seasoncodes(
    output_dir: Path,
    seasoncodes: list[str],
    *,
    k_factor: float = DEFAULT_K,
    initial_rating: float = DEFAULT_INITIAL,
    output_name: str = "elo_multiseason.json",
) -> dict[str, Any]:
    """Compute Elo across a consecutive list of seasoncodes and persist one payload."""
    if not seasoncodes:
        raise ValueError("seasoncodes must not be empty")

    uniq_sorted = sorted(set(seasoncodes), key=lambda s: _seasoncode_year(s) or 0)
    if not are_consecutive_seasoncodes(uniq_sorted):
        missing = missing_seasoncodes_in_range(uniq_sorted)
        msg = "seasoncodes must be consecutive"
        if missing:
            msg += f" (missing: {', '.join(missing)})"
        raise ValueError(msg)

    games = _collect_games_for_seasoncodes(output_dir, uniq_sorted)
    games.sort(
        key=lambda g: (
            _seasoncode_year(str(g.get("seasoncode") or "")) or 0,
            _parse_gamedate(g.get("gamedate")),
            int(g.get("gamecode") or 0),
        )
    )

    ratings, history = compute_elo_from_games(
        games,
        k_factor=k_factor,
        initial_rating=initial_rating,
        sort_games=False,
    )

    payload: dict[str, Any] = {
        "mode": "multi_season",
        "seasoncodes": uniq_sorted,
        "season_labels": [season_label_from_code(s) for s in uniq_sorted],
        "k_factor": k_factor,
        "initial_rating": initial_rating,
        "ratings": ratings,
        "history": history,
    }

    out_path = output_dir / output_name
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote multi-season ELO with {len(history)} games -> {out_path}")
    return payload


def should_recompute_multiseason_elo(
    output_dir: Path,
    *,
    output_name: str = "elo_multiseason.json",
) -> tuple[bool, list[str], str]:
    """Check whether stored seasons and existing ELO payload are aligned.

    Returns:
      (should_recompute, discovered_seasoncodes, reason)
    """
    seasons = discover_stored_seasoncodes(output_dir)
    if not seasons:
        return False, [], "no stored seasons found"

    if not are_consecutive_seasoncodes(seasons):
        missing = missing_seasoncodes_in_range(seasons)
        if missing:
            return False, seasons, f"stored seasons are not consecutive (missing: {', '.join(missing)})"
        return False, seasons, "stored seasons are not consecutive"

    elo_path = output_dir / output_name
    if not elo_path.exists():
        return True, seasons, f"missing {output_name}"

    try:
        payload = json.loads(elo_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True, seasons, f"{output_name} is invalid JSON"

    current = payload.get("seasoncodes")
    if not isinstance(current, list):
        return True, seasons, f"{output_name} missing seasoncodes"

    current_norm = sorted({str(s) for s in current}, key=lambda s: _seasoncode_year(s) or 0)
    if current_norm != seasons:
        return True, seasons, "seasoncodes mismatch with stored data"

    return False, seasons, "up-to-date"


def recompute_multiseason_elo_if_needed(
    output_dir: Path,
    *,
    k_factor: float = DEFAULT_K,
    initial_rating: float = DEFAULT_INITIAL,
    force: bool = False,
    output_name: str = "elo_multiseason.json",
) -> tuple[bool, dict[str, Any] | None, str]:
    """Recompute multi-season Elo when coverage is stale/missing.

    Returns:
      (recomputed, payload_or_none, reason)
    """
    should, seasons, reason = should_recompute_multiseason_elo(output_dir, output_name=output_name)
    if not seasons:
        return False, None, reason

    if (not should) and (not force):
        return False, None, reason

    payload = compute_elo_for_seasoncodes(
        output_dir=output_dir,
        seasoncodes=seasons,
        k_factor=k_factor,
        initial_rating=initial_rating,
        output_name=output_name,
    )
    return True, payload, "recomputed"
