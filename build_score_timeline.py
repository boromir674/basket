from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

VALID_ACTIONS = {"FTM", "FTA", "2FGM", "2FGA", "3FGM", "3FGA"}


def _classify_action(id_action: str | None) -> tuple[str, bool, int] | None:
    if not id_action:
        return None
    action = id_action.strip().upper()
    if action not in VALID_ACTIONS:
        return None

    if action.startswith("FT"):
        shot_type = "ft"
        points = 1 if action.endswith("M") else 0
    elif action.startswith("2FG"):
        shot_type = "two"
        points = 2 if action.endswith("M") else 0
    else:
        shot_type = "three"
        points = 3 if action.endswith("M") else 0

    is_make = action.endswith("M")
    return shot_type, is_make, points


def _infer_home_away(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    home_team = None
    away_team = None
    prev_a = 0
    prev_b = 0

    for row in rows:
        if _classify_action(row.get("ID_ACTION")) is None:
            continue
        pts_a = row.get("POINTS_A") or 0
        pts_b = row.get("POINTS_B") or 0
        team = (row.get("TEAM") or "").strip()
        if pts_a > prev_a and home_team is None:
            home_team = team
        if pts_b > prev_b and away_team is None:
            away_team = team
        prev_a = pts_a
        prev_b = pts_b
        if home_team and away_team:
            break

    return home_team, away_team


def _state_label(diff_a_minus_b: int) -> str:
    if diff_a_minus_b > 0:
        return "leading"
    if diff_a_minus_b < 0:
        return "trailing"
    return "tied"


def build_timeline_payload(raw_points_path: Path) -> dict[str, Any]:
    raw = json.loads(raw_points_path.read_text(encoding="utf-8"))
    rows = raw.get("Rows") if isinstance(raw, dict) else []
    if not isinstance(rows, list):
        rows = []

    season_game = re.match(r"raw_pts_(E\d{4})_(\d+)\.json$", raw_points_path.name)
    seasoncode = season_game.group(1) if season_game else None
    gamecode = int(season_game.group(2)) if season_game else None

    home_team, away_team = _infer_home_away(rows)

    events: list[dict[str, Any]] = []
    prev_a = 0
    prev_b = 0

    for row in rows:
        parsed = _classify_action(row.get("ID_ACTION"))
        if parsed is None:
            continue

        shot_type, is_make, points = parsed
        team_code = (row.get("TEAM") or "").strip()
        side = "home" if team_code == home_team else "away"

        pts_a = int(row.get("POINTS_A") or 0)
        pts_b = int(row.get("POINTS_B") or 0)
        diff_before = prev_a - prev_b
        diff_after = pts_a - pts_b

        event = {
            "num_anot": int(row.get("NUM_ANOT") or 0),
            "minute": float(row.get("MINUTE") or 0),
            "console": row.get("CONSOLE") or "",
            "team_code": team_code,
            "team_side": side,
            "id_action": (row.get("ID_ACTION") or "").strip().upper(),
            "shot_type": shot_type,
            "is_attempt": True,
            "is_make": bool(is_make),
            "points": int(points),
            "points_a": pts_a,
            "points_b": pts_b,
            "diff_a_minus_b_before": int(diff_before),
            "diff_a_minus_b_after": int(diff_after),
            "state_for_a_before": _state_label(diff_before),
            "state_for_b_before": _state_label(-diff_before),
            "utc": row.get("UTC") or "",
        }
        events.append(event)
        prev_a = pts_a
        prev_b = pts_b

    final_a = events[-1]["points_a"] if events else 0
    final_b = events[-1]["points_b"] if events else 0

    return {
        "meta": {
            "seasoncode": seasoncode,
            "gamecode": gamecode,
            "raw_file": raw_points_path.name,
            "home_team_code": home_team,
            "away_team_code": away_team,
            "score_a": final_a,
            "score_b": final_b,
            "winner_side": "home" if final_a > final_b else ("away" if final_b > final_a else "tied"),
            "events": len(events),
        },
        "events": events,
    }


def _iter_raw_points_files(raw_dir: Path, seasoncode: str | None, gamecodes: set[int] | None) -> list[Path]:
    files = sorted(raw_dir.glob("raw_pts_E*_*.json"))
    selected: list[Path] = []
    for path in files:
        m = re.match(r"raw_pts_(E\d{4})_(\d+)\.json$", path.name)
        if not m:
            continue
        sc = m.group(1)
        gc = int(m.group(2))
        if seasoncode and sc != seasoncode:
            continue
        if gamecodes and gc not in gamecodes:
            continue
        selected.append(path)
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build score_timeline JSON files from raw_pts data.")
    parser.add_argument("--seasoncode", default=None, help="Season code filter, e.g. E2025")
    parser.add_argument(
        "--gamecode",
        action="append",
        default=[],
        help="Game code filter(s), can repeat or pass comma-separated values",
    )
    parser.add_argument("--raw-dir", default="assets", help="Directory containing raw_pts_*.json")
    parser.add_argument("--output-dir", default="data", help="Directory for score_timeline_*.json outputs")
    args = parser.parse_args(argv)

    gamecodes: set[int] | None = None
    if args.gamecode:
        gamecodes = set()
        for token in args.gamecode:
            for part in token.split(","):
                part = part.strip()
                if not part:
                    continue
                gamecodes.add(int(part))

    raw_dir = Path(args.raw_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_raw_points_files(raw_dir, args.seasoncode, gamecodes)
    if not files:
        print("No raw_pts files matched the filters.")
        return 0

    written = 0
    for raw_file in files:
        payload = build_timeline_payload(raw_file)
        seasoncode = payload["meta"].get("seasoncode") or "UNK"
        gamecode = payload["meta"].get("gamecode") or 0
        out_name = f"score_timeline_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written += 1

    print(f"Wrote {written} score timeline file(s) to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
