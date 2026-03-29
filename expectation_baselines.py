"""expectation_baselines.py — season-level EPV baseline enrichment.

Scans processed game files for a given season, aggregates team-season and
league-wide expectation baselines, and writes an enriched sibling JSON with
the ``baselines`` sub-tree of each team's ``expectation`` block populated.

Usage (standalone)::

    python expectation_baselines.py \\
        --game assets/processed/multi_drilldown_real_data_E2021_54.json \\
        --seasoncode E2021 \\
        --data-dir assets/processed

Or import and call ``run_expectation_baselines_for_game`` from Python.

The output file has the suffix ``_epv.json`` and is a full copy of the source
game JSON with the ``expectation.teams.<team>.baselines`` sub-trees filled in
where enough sample games exist.  When fewer than ``MIN_BASELINE_GAMES``
comparison games are available the corresponding baseline entry is set to
``{"status": "insufficient_sample", "n_games": <int>}`` rather than unstable
statistics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

_SHOT_FAMILIES = ("all", "ft", "2pt", "3pt")
_TIME_WINDOWS = ("full_game", "last_4_min")
MIN_BASELINE_GAMES = 3  # minimum comparison games for a stable baseline


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Baseline aggregation
# ---------------------------------------------------------------------------

def _extract_ev_samples(
    game: Dict[str, Any],
    team: str,
    window: str,
    family: str,
) -> Optional[float]:
    """Return the ev value for a given (team, window, family) triple, or None."""
    try:
        ev = game["expectation"]["teams"][team][window][family]["ev"]
        if ev is None:
            return None
        return float(ev)
    except (KeyError, TypeError, ValueError):
        return None


def _baseline_stats(samples: List[float], current_ev: Optional[float]) -> Dict[str, Any]:
    """Compute summary statistics for a list of ev samples."""
    n = len(samples)
    if n < MIN_BASELINE_GAMES:
        return {"status": "insufficient_sample", "n_games": n}
    m = round(mean(samples), 4)
    sd = round(stdev(samples), 4) if n >= 2 else None
    delta = round(current_ev - m, 4) if current_ev is not None else None
    return {
        "n_games": n,
        "mean_ev": m,
        "stdev_ev": sd,
        "delta_vs_baseline": delta,
    }


def _aggregate_timeline_baseline(game_timelines: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Average per-minute-bucket ev values across multiple game timelines.

    Returns a list of dicts with keys: minute_bucket, label, mean_ev, n_games.
    Buckets missing from individual games contribute None and are not counted.
    """
    bucket_evs: Dict[int, List[float]] = {}
    for timeline in game_timelines:
        for bin_entry in timeline:
            b = bin_entry.get("minute_bucket")
            ev = bin_entry.get("ev")
            if b is None or ev is None:
                continue
            bucket_evs.setdefault(b, []).append(float(ev))

    if not bucket_evs:
        return []

    out = []
    for b in sorted(bucket_evs.keys()):
        evs = bucket_evs[b]
        out.append({
            "minute_bucket": b,
            "label": f"Min {b}-{b + 1}",
            "mean_ev": round(mean(evs), 4),
            "n_games": len(evs),
        })
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_expectation_baselines_for_game(
    game_path: str,
    seasoncode: str,
    data_dir: str,
) -> Path:
    """Enrich a processed game JSON with team-season and league-season EPV baselines.

    Reads ``game_path``, discovers sibling files for the same season in
    ``data_dir``, computes baselines, and writes an ``_epv.json`` sibling.
    Returns the output path.
    """
    target_path = Path(game_path).resolve()
    base_dir = Path(data_dir).resolve()

    target_game = _load_json(target_path)
    expectation = target_game.get("expectation")
    if not isinstance(expectation, dict) or "teams" not in expectation:
        raise ValueError(
            f"{target_path}: missing or invalid 'expectation' block. "
            "Run build_from_euroleague_api.py first."
        )

    meta = target_game.get("meta") or {}
    team_a = meta.get("team_a", "")
    team_b = meta.get("team_b", "")
    teams = [t for t in [team_a, team_b] if t]

    # Discover comparison game files for the same season (exclude target).
    pattern = f"multi_drilldown_real_data_{seasoncode}_"
    comparison_games: List[Dict[str, Any]] = []
    for candidate in sorted(base_dir.glob("multi_drilldown_real_data_*.json")):
        if pattern not in candidate.name:
            continue
        # Exclude _auto.json and _epv.json enrichment siblings.
        if candidate.stem.endswith("_auto") or candidate.stem.endswith("_epv"):
            continue
        if candidate.resolve() == target_path:
            continue
        try:
            game = _load_json(candidate)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(game.get("expectation"), dict):
            comparison_games.append(game)

    print(
        f"[expectation_baselines] Found {len(comparison_games)} comparison game(s) "
        f"for season {seasoncode}."
    )

    # Build baselines per team.
    for team in teams:
        team_block = expectation["teams"].get(team)
        if not isinstance(team_block, dict):
            continue

        baselines: Dict[str, Any] = {}

        # ---- team_season baseline ----
        team_season: Dict[str, Any] = {}
        team_timelines: List[List[Dict[str, Any]]] = []
        for window in _TIME_WINDOWS:
            window_baselines: Dict[str, Any] = {}
            for family in _SHOT_FAMILIES:
                samples = [
                    ev
                    for g in comparison_games
                    for ev in [_extract_ev_samples(g, team, window, family)]
                    if ev is not None
                ]
                current_ev = _extract_ev_samples(target_game, team, window, family)
                window_baselines[family] = _baseline_stats(samples, current_ev)
            team_season[window] = window_baselines
            # Collect timelines from comparison games for this team
            if window == "full_game":
                for g in comparison_games:
                    try:
                        tl = g["expectation"]["teams"][team]["timeline"]
                        if isinstance(tl, list) and tl:
                            team_timelines.append(tl)
                    except (KeyError, TypeError):
                        pass
        if team_timelines:
            team_season["timeline_avg"] = _aggregate_timeline_baseline(team_timelines)
        baselines["team_season"] = team_season

        # ---- league_season baseline ----
        # Use all teams across all comparison games for the same metric/window.
        league_season: Dict[str, Any] = {}
        league_timelines: List[List[Dict[str, Any]]] = []
        for window in _TIME_WINDOWS:
            window_baselines = {}
            for family in _SHOT_FAMILIES:
                # Collect ev from every team in every comparison game.
                samples = []
                for g in comparison_games:
                    g_teams = list((g.get("expectation") or {}).get("teams", {}).keys())
                    for gt in g_teams:
                        ev = _extract_ev_samples(g, gt, window, family)
                        if ev is not None:
                            samples.append(ev)
                current_ev = _extract_ev_samples(target_game, team, window, family)
                window_baselines[family] = _baseline_stats(samples, current_ev)
            league_season[window] = window_baselines
            if window == "full_game":
                for g in comparison_games:
                    g_teams = list((g.get("expectation") or {}).get("teams", {}).keys())
                    for gt in g_teams:
                        try:
                            tl = g["expectation"]["teams"][gt]["timeline"]
                            if isinstance(tl, list) and tl:
                                league_timelines.append(tl)
                        except (KeyError, TypeError):
                            pass
        if league_timelines:
            league_season["timeline_avg"] = _aggregate_timeline_baseline(league_timelines)
        baselines["league_season"] = league_season

        team_block["baselines"] = baselines
        expectation["teams"][team] = team_block

    target_game["expectation"] = expectation

    output_path = target_path.with_name(target_path.stem + "_epv.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(target_game, f, ensure_ascii=False, indent=2)

    print(f"[expectation_baselines] Wrote enriched JSON to {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich a processed game JSON with season-level EPV baselines."
    )
    parser.add_argument("--game", required=True, help="Path to the target game JSON file.")
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2021.")
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Directory containing other processed season game files.",
    )
    args = parser.parse_args()
    run_expectation_baselines_for_game(args.game, args.seasoncode, args.data_dir)


if __name__ == "__main__":
    main()
