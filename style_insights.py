from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

SHOT_TYPES = ("ft", "two", "three")
STATES = ("leading", "trailing", "tied")


def _zero_counter() -> dict[str, float]:
    return {"ft": 0.0, "two": 0.0, "three": 0.0}


def _safe_share(counter: dict[str, float]) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {k: 0.0 for k in SHOT_TYPES}
    return {k: counter.get(k, 0.0) / total for k in SHOT_TYPES}


def _l1_distance(a: dict[str, float], b: dict[str, float]) -> float:
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in SHOT_TYPES)


def _score_from_distance(distance: float) -> float:
    # L1 distance for 3-way shares is in [0, 2]. Map to [0, 100].
    return round(max(0.0, min(100.0, 100.0 * (1.0 - distance / 2.0))), 2)


def _pick_spread_indices(size: int) -> list[int]:
    if size <= 0:
        return []
    if size == 1:
        return [0]
    if size == 2:
        return [0, 1]
    return [0, size // 2, size - 1]


def _format_mix(share: dict[str, float]) -> str:
    return (
        f"3PT {round(share.get('three', 0.0) * 100)}% · "
        f"2PT {round(share.get('two', 0.0) * 100)}% · "
        f"FT {round(share.get('ft', 0.0) * 100)}%"
    )


def _collect_timeline_files(data_dir: Path, seasoncode: str) -> list[Path]:
    pattern = f"score_timeline_{seasoncode}_*.json"
    return sorted(data_dir.glob(pattern))


def _game_code_from_name(path: Path) -> int | None:
    m = re.match(r"score_timeline_E\d{4}_(\d+)\.json$", path.name)
    if not m:
        return None
    return int(m.group(1))


def _build_consistency_evidence(
    seasoncode: str,
    game_rows: list[dict[str, Any]],
    points_overall_share: dict[str, float],
    attempts_overall_share: dict[str, float],
) -> list[dict[str, Any]]:
    if not game_rows:
        return []

    scored = []
    for row in game_rows:
        points_distance = _l1_distance(row["points_share"], points_overall_share)
        attempts_distance = _l1_distance(row["attempts_share"], attempts_overall_share)
        avg_distance = (points_distance + attempts_distance) / 2.0
        scored.append(
            {
                "gamecode": row.get("gamecode"),
                "points_share": row["points_share"],
                "attempts_share": row["attempts_share"],
                "points_l1_distance": round(points_distance, 4),
                "attempts_l1_distance": round(attempts_distance, 4),
                "average_l1_distance": round(avg_distance, 4),
            }
        )

    by_distance_asc = sorted(scored, key=lambda r: (r["average_l1_distance"], r.get("gamecode") or 0))
    indices = _pick_spread_indices(len(by_distance_asc))

    evidence: list[dict[str, Any]] = []
    for idx in indices:
        row = by_distance_asc[idx]
        if idx == 0:
            tag = "most_typical"
            summary = "Closest to this team's baseline shot identity."
        elif idx == len(by_distance_asc) - 1:
            tag = "largest_deviation"
            summary = "Strongest deviation from this team's baseline shot identity."
        else:
            tag = "mid_profile"
            summary = "Middle-of-the-road profile between typical and extreme games."

        evidence.append(
            {
                "seasoncode": seasoncode,
                "gamecode": row.get("gamecode"),
                "evidence_tag": tag,
                "summary": summary,
                "points_mix": row["points_share"],
                "attempts_mix": row["attempts_share"],
                "points_l1_distance": row["points_l1_distance"],
                "attempts_l1_distance": row["attempts_l1_distance"],
                "average_l1_distance": row["average_l1_distance"],
                "quick_text": f"Points mix: {_format_mix(row['points_share'])}",
            }
        )

    return evidence


def _build_adaptability_evidence(
    seasoncode: str,
    game_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not game_rows:
        return []

    scored = []
    for row in game_rows:
        per_state_shift: dict[str, float] = {}
        for state in STATES:
            points_shift = _l1_distance(row["points_state_share"][state], row["points_share"])
            attempts_shift = _l1_distance(row["attempts_state_share"][state], row["attempts_share"])
            per_state_shift[state] = round((points_shift + attempts_shift) / 2.0, 4)

        dominant_state = max(STATES, key=lambda s: per_state_shift[s])
        dominant_shift = per_state_shift[dominant_state]
        avg_shift = round(sum(per_state_shift.values()) / len(STATES), 4)

        scored.append(
            {
                "gamecode": row.get("gamecode"),
                "per_state_shift": per_state_shift,
                "dominant_state": dominant_state,
                "dominant_shift": dominant_shift,
                "average_state_shift": avg_shift,
                "points_share": row["points_share"],
                "attempts_share": row["attempts_share"],
            }
        )

    by_shift_desc = sorted(scored, key=lambda r: (r["average_state_shift"], r.get("gamecode") or 0), reverse=True)
    indices = _pick_spread_indices(len(by_shift_desc))

    evidence: list[dict[str, Any]] = []
    for idx in indices:
        row = by_shift_desc[idx]
        if idx == 0:
            tag = "strongest_adaptation"
            summary = "Largest within-game state-conditioned style shifts."
        elif idx == len(by_shift_desc) - 1:
            tag = "state_stable"
            summary = "Most state-stable profile inside this team's season sample."
        else:
            tag = "mid_adaptation"
            summary = "Balanced adaptation signal between the extremes."

        evidence.append(
            {
                "seasoncode": seasoncode,
                "gamecode": row.get("gamecode"),
                "evidence_tag": tag,
                "summary": summary,
                "dominant_state": row["dominant_state"],
                "dominant_state_shift": row["dominant_shift"],
                "average_state_shift": row["average_state_shift"],
                "state_shift": row["per_state_shift"],
                "points_mix": row["points_share"],
                "attempts_mix": row["attempts_share"],
                "quick_text": f"Largest shift while {row['dominant_state']} (avg shift {row['average_state_shift']}).",
            }
        )

    return evidence


def build_style_insights_for_season(data_dir: Path, seasoncode: str) -> dict[str, Any]:
    timeline_files = _collect_timeline_files(data_dir, seasoncode)

    team_agg: dict[str, Any] = defaultdict(
        lambda: {
            "points_overall": _zero_counter(),
            "attempts_overall": _zero_counter(),
            "points_by_state": {s: _zero_counter() for s in STATES},
            "attempts_by_state": {s: _zero_counter() for s in STATES},
        }
    )

    team_game_shares: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for timeline_file in timeline_files:
        payload = json.loads(timeline_file.read_text(encoding="utf-8"))
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            continue

        per_game_counters: dict[str, Any] = defaultdict(
            lambda: {
                "points": _zero_counter(),
                "attempts": _zero_counter(),
                "points_by_state": {s: _zero_counter() for s in STATES},
                "attempts_by_state": {s: _zero_counter() for s in STATES},
            }
        )

        for event in events:
            if not isinstance(event, dict):
                continue
            shot_type = event.get("shot_type")
            if shot_type not in SHOT_TYPES:
                continue
            side = event.get("team_side")
            team_code = event.get("team_code")
            if side not in {"home", "away"} or not team_code:
                continue

            state_key = "state_for_a_before" if side == "home" else "state_for_b_before"
            state = event.get(state_key)
            if state not in STATES:
                state = "tied"

            points = float(event.get("points") or 0.0)
            team_agg[team_code]["points_overall"][shot_type] += points
            team_agg[team_code]["attempts_overall"][shot_type] += 1.0
            team_agg[team_code]["points_by_state"][state][shot_type] += points
            team_agg[team_code]["attempts_by_state"][state][shot_type] += 1.0

            per_game_counters[team_code]["points"][shot_type] += points
            per_game_counters[team_code]["attempts"][shot_type] += 1.0
            per_game_counters[team_code]["points_by_state"][state][shot_type] += points
            per_game_counters[team_code]["attempts_by_state"][state][shot_type] += 1.0

        gamecode = _game_code_from_name(timeline_file)
        for team_code, counters in per_game_counters.items():
            team_game_shares[team_code].append(
                {
                    "gamecode": gamecode,
                    "points_share": _safe_share(counters["points"]),
                    "attempts_share": _safe_share(counters["attempts"]),
                    "points_state_share": {s: _safe_share(counters["points_by_state"][s]) for s in STATES},
                    "attempts_state_share": {s: _safe_share(counters["attempts_by_state"][s]) for s in STATES},
                }
            )

    teams: list[dict[str, Any]] = []
    for team_code in sorted(team_agg.keys()):
        agg = team_agg[team_code]
        points_overall_share = _safe_share(agg["points_overall"])
        attempts_overall_share = _safe_share(agg["attempts_overall"])

        points_state_shares = {s: _safe_share(agg["points_by_state"][s]) for s in STATES}
        attempts_state_shares = {s: _safe_share(agg["attempts_by_state"][s]) for s in STATES}

        game_rows = team_game_shares.get(team_code, [])
        if game_rows:
            avg_points_distance = sum(_l1_distance(r["points_share"], points_overall_share) for r in game_rows) / len(game_rows)
            avg_attempts_distance = sum(_l1_distance(r["attempts_share"], attempts_overall_share) for r in game_rows) / len(game_rows)
        else:
            avg_points_distance = 2.0
            avg_attempts_distance = 2.0

        consistency_score = _score_from_distance(avg_attempts_distance)

        adaptability_distances = []
        for state in STATES:
            adaptability_distances.append(_l1_distance(points_state_shares[state], points_overall_share))
            adaptability_distances.append(_l1_distance(attempts_state_shares[state], attempts_overall_share))
        adaptability_score = round(min(100.0, (sum(adaptability_distances) / max(1, len(adaptability_distances))) * 50.0), 2)

        consistency_evidence = _build_consistency_evidence(
            seasoncode=seasoncode,
            game_rows=game_rows,
            points_overall_share=points_overall_share,
            attempts_overall_share=attempts_overall_share,
        )
        adaptability_evidence = _build_adaptability_evidence(
            seasoncode=seasoncode,
            game_rows=game_rows,
        )

        exemplar_games = [
            {
                "gamecode": row.get("gamecode"),
                "points_share": row.get("points_mix"),
                "attempts_share": row.get("attempts_mix"),
                "summary": row.get("summary"),
            }
            for row in consistency_evidence
        ]

        insight_lines = [
            f"Identity (points): 3PT {round(points_overall_share['three'] * 100)}%, 2PT {round(points_overall_share['two'] * 100)}%, FT {round(points_overall_share['ft'] * 100)}%.",
            f"Consistency score (attempt profile): {consistency_score} / 100.",
            f"Adaptability score: {adaptability_score} / 100.",
        ]

        teams.append(
            {
                "team_code": team_code,
                "consistency_score": consistency_score,
                "adaptability_score": adaptability_score,
                "style": {
                    "points_overall_share": points_overall_share,
                    "attempts_overall_share": attempts_overall_share,
                    "points_state_share": points_state_shares,
                    "attempts_state_share": attempts_state_shares,
                },
                "evidence": {
                    "consistency": consistency_evidence,
                    "adaptability": adaptability_evidence,
                },
                "exemplar_games": exemplar_games,
                "insights": insight_lines,
            }
        )

    by_consistency = sorted(teams, key=lambda t: t["consistency_score"], reverse=True)
    by_adaptability = sorted(teams, key=lambda t: t["adaptability_score"], reverse=True)

    return {
        "meta": {
            "seasoncode": seasoncode,
            "games_scanned": len(timeline_files),
            "teams": len(teams),
            "notes": [
                "Consistency is modeled from attempts-share stability (inverse average L1 distance vs attempts baseline).",
                "Adaptability is modeled as average context-to-baseline distance across leading/trailing/tied.",
            ],
        },
        "rankings": {
            "consistency": [{"team_code": t["team_code"], "score": t["consistency_score"]} for t in by_consistency],
            "adaptability": [{"team_code": t["team_code"], "score": t["adaptability_score"]} for t in by_adaptability],
        },
        "teams": teams,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build style insights JSON from score_timeline files.")
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
    parser.add_argument("--data-dir", default="data", help="Directory containing score_timeline_*.json")
    parser.add_argument("--output-dir", default="data", help="Directory for style_insights_*.json output")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_style_insights_for_season(data_dir, args.seasoncode)
    out_path = output_dir / f"style_insights_{args.seasoncode}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote style insights: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
