from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

BASE = "https://live.euroleague.net/api"

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

def normalize_team_name(raw: Optional[str]) -> str:
    if raw is None:
        return "Unknown"
    s = str(raw).strip()
    return s or "Unknown"

def safe_json_get(url: str, params: dict[str, Any]) -> Any:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_sources(seasoncode: str, gamecode: int):
    params = {"seasoncode": seasoncode, "gamecode": gamecode}
    pbp = safe_json_get(f"{BASE}/PlaybyPlay", params)
    pts = safe_json_get(f"{BASE}/Points", params)
    try:
        box = safe_json_get(f"{BASE}/Boxscore", params)
    except Exception:
        box = {}

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

def extract_pbp_rows(pbp_json: Any) -> list[dict]:
    if isinstance(pbp_json, dict):
        # "ForthQuarter" (misspelling) appears in some EuroLeague API responses;
        # "FourthQuarter" is the corrected spelling. Both are included for compatibility.
        quarter_keys = [
            ("FirstQuarter", 1),
            ("SecondQuarter", 2),
            ("ThirdQuarter", 3),
            ("ForthQuarter", 4),   # API misspelling variant
            ("FourthQuarter", 4),  # Correct spelling variant
            ("ExtraTime", 5),
        ]
        rows = []
        seen_quarter_keys: set[str] = set()
        for q_key, q_num in quarter_keys:
            if q_key in seen_quarter_keys:
                continue
            if q_key in pbp_json and isinstance(pbp_json[q_key], list):
                seen_quarter_keys.add(q_key)
                for row in pbp_json[q_key]:
                    annotated = dict(row) if isinstance(row, dict) else row
                    if isinstance(annotated, dict) and "_quarter" not in annotated:
                        annotated["_quarter"] = q_num
                    rows.append(annotated)
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

# Regulation game duration in EuroLeague (4 × 10 min = 40 min)
REGULATION_SECONDS = 40 * 60
LAST_N_MINUTES = 4
LAST_N_SECONDS = LAST_N_MINUTES * 60


def row_game_clock_seconds(row: dict) -> Optional[int]:
    """Extract game elapsed time as total seconds from game start.

    EuroLeague PBP rows may encode time in several ways:
    - MINUTE (int) + SECOND (int): raw fields
    - GT (str): "MM:SS" or "M:SS" game-time string
    Falls back to None if no parseable time field is found.
    """
    if not isinstance(row, dict):
        return None
    # Try "GT" style "MM:SS"
    gt = first_key(row, ["GT", "gt", "GameTime", "GAMETIME", "gametime"], None)
    if gt is not None:
        s = str(gt).strip()
        if ":" in s:
            parts = s.split(":")
            try:
                return int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                pass
    # Try separate MINUTE + SECOND fields
    minute = first_key(row, ["MINUTE", "minute", "Minute", "MIN_GAME", "min"], None)
    if minute is not None:
        try:
            m = int(float(str(minute)))
            second = first_key(row, ["SECOND", "second", "Second", "SEC", "sec"], None)
            s = int(float(str(second))) if second is not None else 0
            return m * 60 + s
        except (ValueError, TypeError):
            pass
    return None


def classify_shot_family(play_type: str) -> str:
    """Map a raw PBP play-type code to an expectation shot family.

    Returns one of: "2pt", "3pt", "ft", "to", or "other".
    """
    if play_type in MADE_2_CODES or play_type in MISSED_2_CODES:
        return "2pt"
    if play_type in MADE_3_CODES or play_type in MISSED_3_CODES:
        return "3pt"
    if play_type in FT_MADE_CODES or play_type in FT_ATTEMPT_CODES:
        return "ft"
    if play_type in TURNOVER_CODES:
        return "to"
    return "other"

@dataclass
class Possession:
    team: str
    origin: str
    terminal: str
    points: int
    number_of_play: Optional[int] = None
    player_id: Optional[str] = None
    player_name: Optional[str] = None
    # Expectation-value enrichment fields (set during infer_possessions)
    game_clock_seconds: Optional[int] = None  # total seconds elapsed from game start
    minute_bucket: Optional[int] = None       # floor(game_clock_seconds / 60)
    quarter: Optional[int] = None             # 1–4 for regulation, 5+ for OT
    shot_family: Optional[str] = None         # "2pt", "3pt", "ft", "to", or "other"
    opponent_team: Optional[str] = None       # opposing team name

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

def infer_possessions(pbp_rows: list[dict], team_a: Optional[str] = None, team_b: Optional[str] = None):
    """Infer possessions from a flat list of PBP rows.

    When team_a and team_b are provided, the opponent_team field of each
    Possession is populated so downstream expectation aggregations can apply
    opponent-conditioned filters.
    """
    possessions = []
    current_origin_by_team = defaultdict(lambda: "Half-court")
    team_pair = {team_a: team_b, team_b: team_a} if team_a and team_b else {}
    for i, row in enumerate(pbp_rows):
        pt = row_play_type(row)
        team = row_team(row)
        nop = row_number_of_play(row)
        pid, pname = row_player(row)
        clock = row_game_clock_seconds(row)
        quarter = row.get("_quarter") if isinstance(row, dict) else None

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
            p = Possession(team, current_origin_by_team[team], "Turnover", 0, nop, pid, pname)
            p.game_clock_seconds = clock
            p.minute_bucket = (clock // 60) if clock is not None else None
            p.quarter = quarter
            p.shot_family = "to"
            p.opponent_team = team_pair.get(team)
            possessions.append(p)
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

        p = Possession(team, current_origin_by_team[team], terminal, pts, nop, pid, pname)
        p.game_clock_seconds = clock
        p.minute_bucket = (clock // 60) if clock is not None else None
        p.quarter = quarter
        p.shot_family = classify_shot_family(pt)
        p.opponent_team = team_pair.get(team)
        possessions.append(p)
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


# ---------------------------------------------------------------------------
# Expectation value (EPV) helpers
# ---------------------------------------------------------------------------

_SHOT_FAMILIES = ("all", "ft", "2pt", "3pt")
_MIN_SAMPLE_THRESHOLD = 5  # below this, mark result as insufficient_sample


def _epv_metrics(subset: list[Possession]) -> dict[str, Any]:
    """Compute raw expectation metrics for a filtered possession list."""
    n = len(subset)
    if n == 0:
        return {"n": 0, "pts_sum": 0, "ev": None}
    pts_sum = sum(p.points for p in subset)
    return {"n": n, "pts_sum": pts_sum, "ev": round(pts_sum / n, 4)}


def _filter_by_family(possessions: list[Possession], family: str) -> list[Possession]:
    if family == "all":
        return possessions
    return [p for p in possessions if p.shot_family == family]


def build_possession_timeline(possessions: list[Possession]) -> list[dict[str, Any]]:
    """Group possessions into 1-minute clock buckets and compute per-bin metrics.

    Each bin includes: minute_bucket, label, n, pts_sum, ev (per-bin),
    cumulative_n, cumulative_pts, cumulative_ev.
    Possessions without a game_clock_seconds value are excluded from the
    timeline but still count toward overall totals.
    """
    bins: dict[int, list[Possession]] = defaultdict(list)
    for p in possessions:
        if p.minute_bucket is not None:
            bins[p.minute_bucket].append(p)

    if not bins:
        return []

    max_bucket = max(bins.keys())
    timeline = []
    cum_n = 0
    cum_pts = 0
    for b in range(max_bucket + 1):
        bucket_poss = bins.get(b, [])
        n = len(bucket_poss)
        pts = sum(p.points for p in bucket_poss)
        cum_n += n
        cum_pts += pts
        timeline.append({
            "minute_bucket": b,
            "label": f"Min {b}-{b + 1}",
            "n": n,
            "pts_sum": pts,
            "ev": round(pts / n, 4) if n > 0 else None,
            "cumulative_n": cum_n,
            "cumulative_pts": cum_pts,
            "cumulative_ev": round(cum_pts / cum_n, 4) if cum_n > 0 else None,
        })
    return timeline


def build_expectation_block(team_a: str, team_b: str, possessions: list[Possession]) -> dict[str, Any]:
    """Build the top-level ``expectation`` block for a processed game JSON.

    Structure::

        {
          "filter_doc": { ... },
          "teams": {
            "<team>": {
              "full_game":  { "all": {...}, "ft": {...}, "2pt": {...}, "3pt": {...} },
              "last_4_min": { "all": {...}, "ft": {...}, "2pt": {...}, "3pt": {...} },
              "timeline": [ { "minute_bucket": 0, ... }, ... ],
              "baselines": { "team_season": null, "league_season": null }
            }
          }
        }

    The ``baselines`` sub-tree is intentionally null here; it is populated by
    ``expectation_baselines.py`` in a subsequent enrichment pass (similar to
    how ``auto_insights.py`` enriches insight text).
    """
    filter_doc = {
        "denominator_rule": (
            "Count of possessions in the filtered set. "
            "Denominator is never total game possessions unless filter is all possessions."
        ),
        "shot_families": {
            "all": "all possessions regardless of shot type",
            "ft": "possessions ending in a free-throw sequence (FTM or FTA terminal)",
            "2pt": "possessions with a 2-point attempt terminal (made or missed: 2FGM or 2FGA)",
            "3pt": "possessions with a 3-point attempt terminal (made or missed: 3FGM or 3FGA)",
        },
        "time_windows": {
            "full_game": "all possessions in the game",
            "last_4_min": (
                f"possessions whose game clock >= {REGULATION_SECONDS - LAST_N_SECONDS} s "
                f"(final {LAST_N_MINUTES} minutes of regulation)"
            ),
        },
        "poc_assumptions": [
            "Metric is empirical outcome-rate expectation, not a shot-quality model.",
            "Turnover possessions count in 'all' denominator with 0 points.",
            "Turnovers are excluded from shot-family filters (ft/2pt/3pt).",
        ],
    }

    teams_out: dict[str, Any] = {}
    for team in [team_a, team_b]:
        team_poss = [p for p in possessions if p.team == team]
        last4_poss = [
            p for p in team_poss
            if p.game_clock_seconds is not None
            and p.game_clock_seconds >= REGULATION_SECONDS - LAST_N_SECONDS
        ]

        windows = {
            "full_game": team_poss,
            "last_4_min": last4_poss,
        }

        window_metrics: dict[str, Any] = {}
        for window_name, window_poss in windows.items():
            family_metrics: dict[str, Any] = {}
            for family in _SHOT_FAMILIES:
                subset = _filter_by_family(window_poss, family)
                m = _epv_metrics(subset)
                if 0 < m["n"] < _MIN_SAMPLE_THRESHOLD:
                    m["note"] = "low_sample"
                family_metrics[family] = m
            window_metrics[window_name] = family_metrics

        teams_out[team] = {
            **window_metrics,
            "timeline": build_possession_timeline(team_poss),
            "baselines": {
                "team_season": None,
                "league_season": None,
            },
        }

    return {"filter_doc": filter_doc, "teams": teams_out}

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


def extract_game_date(box_json: Any, pbp_json: Any) -> Optional[str]:
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
            return str(candidate)

    if isinstance(pbp_json, dict):
        meta = pbp_json.get("Game") or pbp_json.get("Meta") or {}
        if isinstance(meta, dict):
            candidate = first_key(
                meta,
                ["GameDate", "GAMEDATE", "UtcDate", "utcDate", "gamedate"],
                None,
            )
            if candidate:
                return str(candidate)

    return None

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
    possessions = infer_possessions(pbp_rows, team_a=team_a, team_b=team_b)
    print_diagnostics(pbp_rows, points_rows, possessions)

    game_date = extract_game_date(box_json, pbp_json)
    synced_at = datetime.now(timezone.utc).isoformat()

    out = {
        "meta":{
            "seasoncode": seasoncode,
            "gamecode": gamecode,
            "team_a": team_a,
            "team_b": team_b,
            "gamedate": game_date,
            "synced_at": synced_at,
            "source_endpoints": ["PlaybyPlay","Points","Boxscore"]
        },
        "players": build_players_index(possessions),
        "boxscore_players": extract_boxscore_players(box_json),
        "colors": {team_a:"#d62839", team_b:"#3a86ff"},
        "views": build_views(team_a, team_b, possessions, points_rows),
        "expectation": build_expectation_block(team_a, team_b, possessions),
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
