from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

BASE = "https://live.euroleague.net/api"

# First-class club normalization/validation layer (see src/basket/clubs.py).
from basket.clubs import normalize_team_name as canonicalize_team_name

def first_key(d: dict, keys: list[str], default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def as_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def normalize_team_name(raw: Optional[str]) -> str:  # noqa: D401
    """Canonicalize upstream team names into stable internal club identities."""
    return canonicalize_team_name(raw)

def safe_json_get(url: str, params: dict[str, Any]) -> Any:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:  # JSONDecodeError — empty body or HTML from API for missing gamecodes
        return {}

def fetch_sources(seasoncode: str, gamecode: int):
    params = {"seasoncode": seasoncode, "gamecode": gamecode}
    endpoints = {
        "pbp": f"{BASE}/PlaybyPlay",
        "pts": f"{BASE}/Points",
        "box": f"{BASE}/Boxscore",
    }
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(safe_json_get, url, params): key for key, url in endpoints.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:  # noqa: BLE001
                errors[key] = exc
                results[key] = {}

    pbp = results.get("pbp", {})
    pts = results.get("pts", {})
    box = results.get("box", {})

    # Both primary sources empty → this gamecode does not exist in the API (playoff slot
    # never played, season gap, etc.). Raise so the caller skips it permanently.
    # Re-raise the pbp error if one caused the miss (e.g. transient HTTP error).
    if not pbp and not pts:
        if "pbp" in errors:
            raise errors["pbp"]
        raise ValueError("game not available")

    # Save raw data to the specified directory
    output_dir = Path(os.getenv("BASKET_APP_FILE_STORE_URI", "assets"))
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / f"raw_pbp_{seasoncode}_{gamecode}.json", "w") as f:
        json.dump(pbp, f, indent=2)
    with open(output_dir / f"raw_pts_{seasoncode}_{gamecode}.json", "w") as f:
        json.dump(pts, f, indent=2)
    with open(output_dir / f"raw_box_{seasoncode}_{gamecode}.json", "w") as f:
        json.dump(box, f, indent=2)

    return pbp, pts, box


def fetch_season_gamecodes(seasoncode: str, *, start: int = 1, gap_limit: int = 10) -> list[int]:
    """Discover all valid gamecodes for a season by probing the API.

    Scans gamecodes starting from `start`, stopping after `gap_limit` consecutive
    missing gamecodes (playoff slots never played, end of season, etc.).
    Returns the list of gamecodes that have actual data.
    """
    valid: list[int] = []
    consecutive_missing = 0
    gamecode = start
    while True:
        params = {"seasoncode": seasoncode, "gamecode": gamecode}
        pbp = safe_json_get(f"{BASE}/PlaybyPlay", params)
        pts = safe_json_get(f"{BASE}/Points", params)
        if pbp or pts:
            valid.append(gamecode)
            consecutive_missing = 0
        else:
            consecutive_missing += 1
            if consecutive_missing >= gap_limit:
                break
        gamecode += 1
    return valid

def extract_pbp_rows(pbp_json: Any) -> list[dict]:
    if isinstance(pbp_json, dict):
        quarters = ["FirstQuarter", "SecondQuarter", "ThirdQuarter", "ForthQuarter", "FourthQuarter", "ExtraTime"]
        rows = []
        for q in quarters:
            if q in pbp_json and isinstance(pbp_json[q], list):
                rows.extend(pbp_json[q])
        if rows:
            return rows
        for key in ["PlayByPlay", "Rows", "playByPlay", "items"]:
            if key in pbp_json and isinstance(pbp_json[key], list):
                return pbp_json[key]
    if isinstance(pbp_json, list):
        return pbp_json
    return []

def extract_points_rows(points_json: Any) -> list[dict]:
    if isinstance(points_json, dict):
        for key in ["Rows", "Points", "points", "items"]:
            if key in points_json and isinstance(points_json[key], list):
                return points_json[key]
    if isinstance(points_json, list):
        return points_json
    return []

def extract_team_names(box_json: Any, pbp_rows: list[dict]):
    if isinstance(box_json, dict):
        for pair in [("TeamA", "TeamB"), ("teamA", "teamB"), ("HomeTeam", "AwayTeam"), ("homeTeam", "awayTeam")]:
            a = box_json.get(pair[0])
            b = box_json.get(pair[1])
            if a and b:
                return normalize_team_name(a), normalize_team_name(b)
    teams = []
    for row in pbp_rows[:200]:
        v = first_key(row, ["TEAM", "Team", "team", "TEAM_NAME", "teamName"], None)
        if v:
            n = normalize_team_name(v)
            if n not in teams:
                teams.append(n)
        if len(teams) >= 2:
            return teams[0], teams[1]
    return "Team A", "Team B"

def row_play_type(row: dict) -> str:
    return str(first_key(row, ["PlayType", "PLAYTYPE", "playType", "Type", "type"], "")).strip()

def row_team(row: dict) -> str:
    return normalize_team_name(first_key(row, ["TEAM", "Team", "team", "TEAM_NAME", "teamName"], "Unknown"))

def row_number_of_play(row: dict) -> Optional[int]:
    v = first_key(row, ["NumberOfPlay", "NUMBEROFPLAY", "numberOfPlay", "playNumber", "PlayNumber"], None)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None

def normalize_player_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None

def normalize_player_name(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None

def row_player(row: dict) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(row, dict):
        return None, None
    pid = normalize_player_id(first_key(row, ["PLAYER_ID", "ID_PLAYER", "player_id", "playerId"], None))
    pname = normalize_player_name(first_key(row, ["PLAYER", "player", "Player"], None))
    return pid, pname

TURNOVER_CODES = {"TO", "OF"}
OREB_CODES = {"O"}
DREB_CODES = {"D"}
STEAL_CODES = {"ST"}

# Map to real PlayType codes observed in diagnostics, e.g. 2FGM/3FGM.
MADE_2_CODES = {"2FGM"}
MISSED_2_CODES = {"2FGA"}
MADE_3_CODES = {"3FGM"}
MISSED_3_CODES = {"3FGA"}
FT_MADE_CODES = {"FTM"}
FT_ATTEMPT_CODES = {"FTA"}

@dataclass
class Possession:
    team: str
    origin: str
    terminal: str
    points: int
    number_of_play: Optional[int] = None
    player_id: Optional[str] = None
    player_name: Optional[str] = None

def classify_terminal(play_type: str):
    if play_type in MADE_2_CODES:
        return "Made 2", 2
    if play_type in MADE_3_CODES:
        return "Made 3", 3
    if play_type in MISSED_2_CODES or play_type in MISSED_3_CODES:
        return "Missed shot", 0
    if play_type in FT_MADE_CODES or play_type in FT_ATTEMPT_CODES:
        return "Shooting foul / FTs", 1 if play_type in FT_MADE_CODES else 0
    return None, 0

def infer_possessions(pbp_rows: list[dict]):
    possessions = []
    current_origin_by_team = defaultdict(lambda: "Half-court")
    for i, row in enumerate(pbp_rows):
        pt = row_play_type(row)
        team = row_team(row)
        nop = row_number_of_play(row)
        pid, pname = row_player(row)

        if pt in STEAL_CODES:
            current_origin_by_team[team] = "Transition / Fast break"
            continue
        if pt in DREB_CODES:
            current_origin_by_team[team] = "Transition / Fast break"
            continue
        if pt in OREB_CODES:
            current_origin_by_team[team] = "After OREB"
            continue
        if pt in TURNOVER_CODES:
            possessions.append(Possession(team, current_origin_by_team[team], "Turnover", 0, nop, pid, pname))
            current_origin_by_team[team] = "Half-court"
            continue

        terminal, pts = classify_terminal(pt)
        if terminal is None:
            continue

        if terminal == "Missed shot":
            next_row = pbp_rows[i+1] if i + 1 < len(pbp_rows) else None
            next_pt = row_play_type(next_row) if next_row else None
            next_team = row_team(next_row) if next_row else None
            if next_row and next_pt in OREB_CODES and next_team == team:
                continue

        possessions.append(Possession(team, current_origin_by_team[team], terminal, pts, nop, pid, pname))
        current_origin_by_team[team] = "Half-court"
    return possessions

def build_points_map(points_rows: list[dict]):
    out = {}
    for r in points_rows:
        nop = first_key(r, ["NumberOfPlay", "NUMBEROFPLAY", "numberOfPlay", "playNumber"], None)
        if nop is None:
            continue
        try:
            out[int(nop)] = r
        except Exception:
            pass
    return out

def shot_zone_label(row):
    if not row:
        return ""
    return str(first_key(row, ["Zone", "ZONE", "zone"], "")).strip()

def coord_x(row):
    if not row:
        return 0.0
    return as_float(first_key(row, ["CoordX", "coordX", "X", "x"], 0.0), 0.0)

def subtype_made2(point_row):
    if not point_row:
        return "Layup / runner"
    zone = shot_zone_label(point_row).lower()
    x = coord_x(point_row)
    if "dunk" in zone:
        return "Dunk / cut finish"
    if "paint" in zone or "restricted" in zone or abs(x) < 80:
        return "Layup / runner"
    return "Midrange jumper"

def subtype_made3(point_row):
    if not point_row:
        return "Above-the-break C&S"
    zone = shot_zone_label(point_row).lower()
    x = coord_x(point_row)
    if "corner" in zone or abs(x) > 620:
        return "Corner catch-and-shoot"
    if "movement" in zone:
        return "Movement / late-clock"
    return "Above-the-break C&S"

def subtype_transition_origin(p):
    return "After defensive rebound" if p.origin == "Transition / Fast break" else "Early offense flow"

def subtype_oreb_origin(p, point_row):
    if p.terminal == "Made 2":
        s = subtype_made2(point_row)
        if s in {"Layup / runner", "Dunk / cut finish"}:
            return "Immediate putback"
    if p.terminal == "Made 3":
        return "Kick-out perimeter"
    return "Reset half-court"

def subtype_halfcourt(p, point_row):
    if p.terminal == "Shooting foul / FTs":
        return "PnR / handler action"
    if p.terminal == "Made 2":
        s = subtype_made2(point_row)
        return "Post / interior touch" if s == "Dunk / cut finish" else "PnR / handler action"
    if p.terminal == "Made 3":
        return "Spot-up / swing"
    return "PnR / handler action"

def add_node(nodes, node_id, name, team, stage):
    if not any(n["id"] == node_id for n in nodes):
        nodes.append({"id": node_id, "name": name, "team": team, "stage": stage})

def counter_to_links(counter):
    return [{"source": s, "target": t, "value": v} for (s, t), v in counter.items() if v > 0]

def node_id(team, name):
    return f"{team}_{name}".replace(" / ", "_").replace(" ", "_")

def possession_player_ref(p: Possession) -> tuple[str, str]:
    """Return stable player id/name for attribution; falls back to Unknown."""
    pid = normalize_player_id(p.player_id)
    pname = normalize_player_name(p.player_name)
    if pid and pname:
        return pid, pname
    if pid and not pname:
        return pid, pid
    if pname and not pid:
        return f"anon::{pname}", pname
    return f"unknown::{p.team}", "Unknown"

def counter_to_player_flows(counter: Counter) -> dict[str, list[dict[str, Any]]]:
    """Convert (source,target,pid,pname,team)->count into link keyed payload."""
    bucketed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (source, target, pid, pname, team), poss in counter.items():
        if poss <= 0:
            continue
        link_key = f"{source}->{target}"
        bucketed[link_key].append(
            {
                "player_id": pid,
                "player_name": pname,
                "team": team,
                "poss": int(poss),
            }
        )
    out: dict[str, list[dict[str, Any]]] = {}
    for link_key, rows in bucketed.items():
        out[link_key] = sorted(rows, key=lambda r: (-int(r.get("poss", 0)), str(r.get("player_name", ""))))
    return out

def build_players_index(possessions: list[Possession]) -> dict[str, dict[str, str]]:
    players: dict[str, dict[str, str]] = {}
    for p in possessions:
        pid, pname = possession_player_ref(p)
        if pid.startswith("unknown::"):
            continue
        players[pid] = {"name": pname, "team": p.team}
    return players

def build_top_view(team_a, team_b, possessions):
    starts = Counter(p.team for p in possessions)
    nodes, links = [], Counter()
    player_flows = Counter()
    for team in [team_a, team_b]:
        add_node(nodes, node_id(team, "start"), f"{team} Start", team, "start")
        for typ in ["Half-court", "Transition / Fast break", "After OREB"]:
            add_node(nodes, node_id(team, typ), typ, team, "type")
        for ev in ["Turnover", "Missed shot", "Shooting foul / FTs", "Made 2", "Made 3"]:
            add_node(nodes, node_id(team, ev), ev, team, "event")
        for pts, label in [(0, "0 pts"), (1, "1 pt"), (2, "2 pts"), (3, "3 pts")]:
            add_node(nodes, f"{team}_{pts}", label, team, "points")
    for p in possessions:
        s = node_id(p.team, "start")
        t = node_id(p.team, p.origin)
        e = node_id(p.team, p.terminal)
        pnode = f"{p.team}_{p.points if p.points in [0,1,2,3] else 0}"
        pid, pname = possession_player_ref(p)
        links[(s,t)] += 1
        links[(t,e)] += 1
        links[(e,pnode)] += 1
        player_flows[(s, t, pid, pname, p.team)] += 1
        player_flows[(t, e, pid, pname, p.team)] += 1
        player_flows[(e, pnode, pid, pname, p.team)] += 1

    # Lightweight, backwards-compatible metrics for the top view.
    totals = {
        team_a: {"pos": 0, "pts": 0, "made2": 0, "made3": 0, "ft": 0, "to": 0},
        team_b: {"pos": 0, "pts": 0, "made2": 0, "made3": 0, "ft": 0, "to": 0},
    }
    for p in possessions:
        if p.team not in totals:
            continue
        bucket = totals[p.team]
        bucket["pos"] += 1
        bucket["pts"] += p.points
        if p.terminal == "Made 2":
            bucket["made2"] += 1
        elif p.terminal == "Made 3":
            bucket["made3"] += 1
        elif p.terminal == "Shooting foul / FTs":
            bucket["ft"] += 1
        elif p.terminal == "Turnover":
            bucket["to"] += 1

    def pct(n: int, d: int) -> str:
        return f"{(100.0 * n / d):.0f}%" if d else "0%"

    kpis: list[list[str]] = [
        [f"{team_a} starts", str(starts[team_a])],
        [f"{team_b} starts", str(starts[team_b])],
    ]

    insights: list[str] = [
        "Possession types are inferred, not native API fields.",
        "This JSON is suitable both for Sankey rendering and later metrics expansion.",
    ]

    for team in [team_a, team_b]:
        bucket = totals[team]
        pos = bucket["pos"]
        pts = bucket["pts"]
        ppp = (pts / pos) if pos else 0.0
        kpis.append([f"{team} points per poss.", f"{ppp:.2f}"])
        kpis.append([
            f"{team} Made 3 share",
            pct(bucket["made3"], pos),
        ])
        if pos:
            insights.append(
                f"{team} generated {ppp:.2f} points per possession over {pos} tracked possessions."
            )
    return {
        "label": "Top-level",
        "starts": {team_a: starts[team_a], team_b: starts[team_b]},
        "title": "Context",
        "desc": "Top-level view derived from Euroleague PlayByPlay + Points endpoints.",
        "kpis": kpis,
        "insights": insights,
        "columns": ["Start", "Possession Type", "Terminal Event", "Points"],
        "nodes": nodes,
        "links": counter_to_links(links),
        "player_flows": counter_to_player_flows(player_flows),
    }

def build_subview(label, title, desc, columns, team_a, team_b, start_name_a, start_name_b, subset, subtype_fn, points_map):
    starts = Counter(p.team for p in subset)
    nodes, links = [], Counter()
    player_flows = Counter()
    typed_rows, subtypes, terminals, point_values = [], set(), set(), set()

    add_node(nodes, node_id(team_a, "start"), start_name_a, team_a, "start")
    add_node(nodes, node_id(team_b, "start"), start_name_b, team_b, "start")

    for p in subset:
        point_row = points_map.get(p.number_of_play) if p.number_of_play is not None else None
        subtype = subtype_fn(p, point_row)
        typed_rows.append((p, subtype))
        subtypes.add(subtype)
        terminals.add(p.terminal)
        point_values.add(p.points if p.points in [0,1,2,3] else 0)

    for team in [team_a, team_b]:
        for st in sorted(subtypes):
            add_node(nodes, node_id(team, st), st, team, "type")
        for ev in sorted(terminals):
            add_node(nodes, node_id(team, ev), ev, team, "event")
        for pts in sorted(point_values):
            add_node(nodes, f"{team}_{pts}", "1 pt" if pts == 1 else f"{pts} pts", team, "points")

    for p, subtype in typed_rows:
        s = node_id(p.team, "start")
        t = node_id(p.team, subtype)
        e = node_id(p.team, p.terminal)
        pnode = f"{p.team}_{p.points if p.points in [0,1,2,3] else 0}"
        pid, pname = possession_player_ref(p)
        links[(s,t)] += 1
        links[(t,e)] += 1
        links[(e,pnode)] += 1
        player_flows[(s, t, pid, pname, p.team)] += 1
        player_flows[(t, e, pid, pname, p.team)] += 1
        player_flows[(e, pnode, pid, pname, p.team)] += 1

    return {
        "label":label,
        "starts":{team_a: starts[team_a], team_b: starts[team_b]},
        "title":title,
        "desc":desc,
        "kpis":[[f"{team_a} count", str(starts[team_a])],[f"{team_b} count", str(starts[team_b])]],
        "insights":[f"{label} derived heuristically from real endpoint data.","Subtype names are inferred categories for the product spike."],
        "columns":columns,
        "nodes":nodes,
        "links":counter_to_links(links),
        "player_flows":counter_to_player_flows(player_flows),
    }

def build_views(team_a, team_b, possessions, points_rows):
    points_map = build_points_map(points_rows)
    views = {"top": build_top_view(team_a, team_b, possessions)}
    half = [p for p in possessions if p.origin == "Half-court"]
    views["halfcourt"] = build_subview("Half-court breakdown","Zoomed Detail — Half-court","Half-court offense broken into inferred action families.",["Start","Half-court Subtype","Terminal Event","Points"],team_a,team_b,f"{team_a} Half-court",f"{team_b} Half-court",half,lambda p,r: subtype_halfcourt(p,r),points_map)
    trans = [p for p in possessions if p.origin == "Transition / Fast break"]
    views["transition"] = build_subview("Transition breakdown","Zoomed Detail — Transition / Fast break","Transition possessions split by inferred origin.",["Start","Transition Origin","Terminal Event","Points"],team_a,team_b,f"{team_a} Transition",f"{team_b} Transition",trans,lambda p,r: subtype_transition_origin(p),points_map)
    oreb = [p for p in possessions if p.origin == "After OREB"]
    views["oreb"] = build_subview("After OREB breakdown","Zoomed Detail — After OREB","Second-chance possessions decomposed by inferred continuation type.",["Start","Second-Chance Type","Terminal Event","Points"],team_a,team_b,f"{team_a} After OREB",f"{team_b} After OREB",oreb,lambda p,r: subtype_oreb_origin(p,r),points_map)
    made2 = [p for p in possessions if p.terminal == "Made 2"]
    views["made2"] = build_subview("Made 2 breakdown","Zoomed Detail — Made 2","Made 2s decomposed by inferred shot subtype from the Points endpoint.",["Start","Made 2 Subtype","Terminal Event","Points"],team_a,team_b,f"{team_a} Made 2",f"{team_b} Made 2",made2,lambda p,r: subtype_made2(r),points_map)
    made3 = [p for p in possessions if p.terminal == "Made 3"]
    views["made3"] = build_subview("Made 3 breakdown","Zoomed Detail — Made 3","Made 3s decomposed by inferred shot subtype from the Points endpoint.",["Start","Made 3 Subtype","Terminal Event","Points"],team_a,team_b,f"{team_a} Made 3",f"{team_b} Made 3",made3,lambda p,r: subtype_made3(r),points_map)
    return views

def print_diagnostics(pbp_rows, points_rows, possessions):
    print("---- Diagnostics ----")
    print("PBP rows:", len(pbp_rows))
    print("Points rows:", len(points_rows))
    print("Possessions inferred:", len(possessions))
    print("Top PlayType counts:", Counter(row_play_type(r) for r in pbp_rows).most_common(15))
    print("Origin counts:", Counter(p.origin for p in possessions))
    print("Terminal counts:", Counter(p.terminal for p in possessions))
    print("---------------------")


def normalize_game_date(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    compact = "".join(ch for ch in text if ch.isdigit())
    if len(compact) >= 8:
        try:
            parsed = datetime.strptime(compact[:8], "%Y%m%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    if len(text) >= 10:
        prefix = text[:10]
        try:
            parsed = datetime.strptime(prefix, "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def extract_game_date(box_json: Any, pbp_json: Any, points_json: Any = None) -> Optional[str]:
    """Best-effort game date from the raw API payloads.

    Returns an ISO-ish string if we find something, otherwise None. This is
    intentionally heuristic and can be tightened later once the API shape
    is more stable.
    """

    if isinstance(box_json, dict):
        candidate = first_key(
            box_json,
            [
                "GameDate",
                "GAMEDATE",
                "UtcDate",
                "utcDate",
                "GameDateUTC",
                "gamedate",
            ],
            None,
        )
        if candidate:
            normalized = normalize_game_date(candidate)
            if normalized:
                return normalized

    if isinstance(pbp_json, dict):
        meta = pbp_json.get("Game") or pbp_json.get("Meta") or {}
        if isinstance(meta, dict):
            candidate = first_key(
                meta,
                ["GameDate", "GAMEDATE", "UtcDate", "utcDate", "gamedate"],
                None,
            )
            if candidate:
                normalized = normalize_game_date(candidate)
                if normalized:
                    return normalized

    points_rows = extract_points_rows(points_json)
    utc_candidates = []
    for row in points_rows:
        if not isinstance(row, dict):
            continue
        candidate = first_key(row, ["UTC", "utc", "Utc", "GameUTC", "gameUtc"], None)
        normalized = normalize_game_date(candidate)
        if normalized:
            utc_candidates.append(normalized)
    if utc_candidates:
        return min(utc_candidates)

    return None

def extract_final_scores(box_json: Any, team_a: str, team_b: str) -> tuple[Optional[int], Optional[int]]:
    """Return (score_a, score_b) by summing per-player points from Boxscore Stats."""
    if not isinstance(box_json, dict):
        return None, None
    stats = box_json.get("Stats")
    if not isinstance(stats, list):
        return None, None
    team_scores: dict[str, int] = {}
    for team_block in stats:
        if not isinstance(team_block, dict):
            continue
        team_name = normalize_team_name(
            first_key(team_block, ["Team", "TEAM", "TeamCode", "teamCode", "TeamName"], None)
        )
        total = team_block.get("totalPoints") or team_block.get("TotalPoints")
        if total is not None:
            try:
                team_scores[team_name] = int(total)
                continue
            except (ValueError, TypeError):
                pass
        # Fall back to summing PlayersStats points
        players = team_block.get("PlayersStats") or []
        pts_sum = 0
        for row in players:
            if not isinstance(row, dict):
                continue
            pts = first_key(row, ["Points", "PTS"], 0) or 0
            try:
                pts_sum += int(pts)
            except (ValueError, TypeError):
                pass
        if team_name != "Unknown":
            team_scores[team_name] = pts_sum
    score_a = team_scores.get(team_a)
    score_b = team_scores.get(team_b)
    return score_a, score_b


def extract_scores_from_boxscore_players(
    boxscore_players: list[dict[str, Any]],
    players_index: dict[str, dict[str, str]],
    team_a: str,
    team_b: str,
) -> tuple[Optional[int], Optional[int]]:
    """Fallback: sum player points using player_id->team name mapping."""
    if not boxscore_players:
        return None, None
    team_points: dict[str, int] = {}
    for row in boxscore_players:
        if not isinstance(row, dict):
            continue
        pid = row.get("player_id")
        pts = row.get("points")
        if pid is None or pts is None:
            continue
        team_name = None
        if pid in players_index:
            team_name = players_index[pid].get("team")
        if not team_name:
            continue
        try:
            team_points[team_name] = team_points.get(team_name, 0) + int(pts)
        except (ValueError, TypeError):
            continue
    return team_points.get(team_a), team_points.get(team_b)


def extract_boxscore_players(box_json: Any) -> list[dict[str, Any]]:
    """Extract compact player stat rows from Boxscore payload when available."""
    out: list[dict[str, Any]] = []
    if not isinstance(box_json, dict):
        return out
    stats = box_json.get("Stats")
    if not isinstance(stats, list):
        return out
    for team_block in stats:
        if not isinstance(team_block, dict):
            continue
        players = team_block.get("PlayersStats")
        if not isinstance(players, list):
            continue
        for row in players:
            if not isinstance(row, dict):
                continue
            pid = normalize_player_id(first_key(row, ["Player_ID", "PLAYER_ID", "ID_PLAYER"], None))
            pname = normalize_player_name(first_key(row, ["Player", "PLAYER"], None))
            team = normalize_team_name(first_key(row, ["Team", "TEAM"], None))
            if not pname:
                continue
            out.append(
                {
                    "player_id": pid or f"anon::{pname}",
                    "player_name": pname,
                    "team": team,
                    "minutes": first_key(row, ["Minutes", "MIN"], None),
                    "points": first_key(row, ["Points", "PTS"], None),
                    "valuation": first_key(row, ["Valuation", "PIR"], None),
                    "plusminus": first_key(row, ["Plusminus", "PlusMinus", "+/-"], None),
                    "assists": first_key(row, ["Assistances", "Assists", "AST"], None),
                    "rebounds": first_key(row, ["TotalRebounds", "REB"], None),
                    "turnovers": first_key(row, ["Turnovers", "TO"], None),
                }
            )
    return out

def run_game(seasoncode: str, gamecode: int, output: str = "multi_drilldown_real_data.json") -> dict:
    """Run the pipeline for a single game and write JSON output.

    Returns the in-memory payload to allow callers (e.g. batch runner) to
    perform lightweight checks or aggregate diagnostics without re-reading
    from disk.
    """

    pbp_json, points_json, box_json = fetch_sources(seasoncode, gamecode)
    pbp_rows = extract_pbp_rows(pbp_json)
    points_rows = extract_points_rows(points_json)
    if not pbp_rows:
        raise SystemExit("No PlayByPlay rows extracted. Adjust extract_pbp_rows().")

    team_a, team_b = extract_team_names(box_json, pbp_rows)
    possessions = infer_possessions(pbp_rows)
    print_diagnostics(pbp_rows, points_rows, possessions)

    game_date = extract_game_date(box_json, pbp_json, points_json)
    synced_at = datetime.now(timezone.utc).isoformat()
    players_index = build_players_index(possessions)
    boxscore_players = extract_boxscore_players(box_json)
    score_a, score_b = extract_final_scores(box_json, team_a, team_b)
    if score_a is None or score_b is None:
        score_a, score_b = extract_scores_from_boxscore_players(
            boxscore_players, players_index, team_a, team_b
        )
    if score_a is not None and score_b is not None:
        if score_a > score_b:
            winner: Optional[str] = team_a
        elif score_b > score_a:
            winner = team_b
        else:
            winner = None
    else:
        winner = None

    out = {
        "meta":{
            "seasoncode": seasoncode,
            "gamecode": gamecode,
            "team_a": team_a,
            "team_b": team_b,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "gamedate": game_date,
            "synced_at": synced_at,
            "source_endpoints": ["PlaybyPlay","Points","Boxscore"]
        },
        "players": players_index,
        "boxscore_players": boxscore_players,
        "colors": {team_a:"#d62839", team_b:"#3a86ff"},
        "views": build_views(team_a, team_b, possessions, points_rows)
    }
    Path(output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {output}")

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasoncode", required=True)
    parser.add_argument("--gamecode", required=True, type=int)
    parser.add_argument("--output", default="multi_drilldown_real_data.json")
    args = parser.parse_args()

    run_game(args.seasoncode, args.gamecode, args.output)

if __name__ == "__main__":
    main()
