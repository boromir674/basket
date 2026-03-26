from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Dict, List


@dataclass
class FeatureStat:
    """Represents a single scalar feature for a specific game.

    The key encodes metric, view (if applicable), and team, e.g.
    "ppp:top:Anadolu Efes Istanbul" or "to_rate:top:Panathinaikos OPAP Athens".
    """

    key: str
    value: float


def _load_json(path: Path) -> Dict[str, Any]:
    # Centralised JSON loader so we can easily add logging or schema checks later.
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _view_names(game: Dict[str, Any]) -> List[str]:
    views = game.get("views") or {}
    if not isinstance(views, dict):
        return []
    # We care primarily about these, but will gracefully ignore missing ones.
    preferred_order = ["top", "halfcourt", "transition", "oreb", "made2", "made3"]
    return [v for v in preferred_order if v in views]


def _points_from_view(view: Dict[str, Any], team: str) -> float:
    """Approximate total points for a team by aggregating points nodes.

    This relies on the convention that point-node ids look like
    "{team}_{pts}" where pts is an integer (0..3).
    """

    total = 0.0
    links = view.get("links") or []
    for link in links:
        target = link.get("target")
        value = link.get("value")
        if not isinstance(target, str) or not isinstance(value, (int, float)):
            continue
        prefix = f"{team}_"
        if not target.startswith(prefix):
            continue
        suffix = target[len(prefix) :]
        try:
            pts = int(suffix)
        except Exception:
            continue
        total += pts * float(value)
    return total


def _extract_ppp_features(game: Dict[str, Any]) -> List[FeatureStat]:
    """Compute points-per-possession per team per view.

    We recompute PPP directly from starts + points so the engine does not
    depend on any pre-existing KPI tiles.
    """

    out: List[FeatureStat] = []
    views = game.get("views") or {}
    for view_name in _view_names(game):
        view = views.get(view_name) or {}
        starts = view.get("starts") or {}
        if not isinstance(starts, dict):
            continue
        for team, raw_starts in starts.items():
            try:
                possessions = float(raw_starts)
            except Exception:
                continue
            if possessions <= 0:
                continue
            pts = _points_from_view(view, team)
            if pts <= 0:
                continue
            ppp = pts / possessions
            out.append(FeatureStat(key=f"ppp:{view_name}:{team}", value=ppp))
    return out


def _fgm_counts(view: Dict[str, Any], team: str) -> Dict[str, float]:
    """Approximate made 2s and 3s using event→points links.

    We look for links where source is the event node and target is a points
    node for the same team. This mirrors how the pipeline encodes Made 2/3.
    """

    made2 = 0.0
    made3 = 0.0
    links = view.get("links") or []
    if not isinstance(links, list):
        return {"made2": 0.0, "made3": 0.0}

    made2_id = f"{team}_Made_2".replace(" / ", "_").replace(" ", "_")
    made3_id = f"{team}_Made_3".replace(" / ", "_").replace(" ", "_")
    for link in links:
        source = link.get("source")
        target = link.get("target")
        value = link.get("value")
        if not isinstance(source, str) or not isinstance(target, str) or not isinstance(value, (int, float)):
            continue
        if source == made2_id:
            made2 += float(value)
        elif source == made3_id:
            made3 += float(value)
    return {"made2": made2, "made3": made3}


def _extract_three_point_share_features(game: Dict[str, Any]) -> List[FeatureStat]:
    """Compute 3P made share among all made field goals per team.

    This is not true 3FGA share but still highlights extreme 3P-heavy or
    3P-light scoring profiles.
    """

    out: List[FeatureStat] = []
    views = game.get("views") or {}
    top = views.get("top") or {}
    starts = top.get("starts") or {}
    if not isinstance(starts, dict):
        return out

    for team in starts.keys():
        counts = _fgm_counts(top, team)
        made2 = counts["made2"]
        made3 = counts["made3"]
        total_made = made2 + made3
        if total_made <= 0:
            continue
        share = made3 / total_made
        out.append(FeatureStat(key=f"fg3_share:top:{team}", value=share))

    return out


def _extract_turnover_rate_features(game: Dict[str, Any]) -> List[FeatureStat]:
    """Compute turnover rate per team using the top view.

    Turnover rate ≈ (turnover possessions / total possessions).
    """

    out: List[FeatureStat] = []
    views = game.get("views") or {}
    top = views.get("top") or {}
    starts = top.get("starts") or {}
    links = top.get("links") or []
    if not isinstance(starts, dict) or not isinstance(links, list):
        return out

    for team, raw_starts in starts.items():
        try:
            possessions = float(raw_starts)
        except Exception:
            continue
        if possessions <= 0:
            continue

        turnover_id = f"{team}_Turnover".replace(" / ", "_").replace(" ", "_")
        turnovers = 0.0
        for link in links:
            source = link.get("source")
            value = link.get("value")
            if not isinstance(source, str) or not isinstance(value, (int, float)):
                continue
            if source == turnover_id:
                turnovers += float(value)
        if turnovers <= 0:
            continue
        rate = turnovers / possessions
        out.append(FeatureStat(key=f"to_rate:top:{team}", value=rate))

    return out


def _extract_oreb_share_features(game: Dict[str, Any]) -> List[FeatureStat]:
    """Compute share of points that come from OREB possessions per team.

    We use the dedicated "oreb" view for OREB-only possessions and compare
    its point total against the top-level view's total points.
    """

    out: List[FeatureStat] = []
    views = game.get("views") or {}
    top = views.get("top") or {}
    oreb = views.get("oreb") or {}
    starts = oreb.get("starts") or {}
    if not isinstance(starts, dict):
        return out

    for team in starts.keys():
        total_top_pts = _points_from_view(top, team)
        if total_top_pts <= 0:
            # If we cannot compute a meaningful denominator, skip this feature.
            continue
        oreb_pts = _points_from_view(oreb, team)
        share = oreb_pts / total_top_pts
        out.append(FeatureStat(key=f"oreb_points_share:top:{team}", value=share))

    return out


def _collect_features(game: Dict[str, Any]) -> List[FeatureStat]:
    # Aggregate all feature families we know about. This keeps the engine
    # self-contained so callers don't need to specify individual metrics.
    feats: List[FeatureStat] = []
    feats.extend(_extract_ppp_features(game))
    feats.extend(_extract_three_point_share_features(game))
    feats.extend(_extract_turnover_rate_features(game))
    feats.extend(_extract_oreb_share_features(game))
    return feats


def _robust_zscore(value: float, samples: List[float]) -> float | None:
    # Robust z-score based on median and MAD so that a few extreme games
    # don't completely dominate the baseline.
    if not samples:
        return None
    m = median(samples)
    deviations = [abs(x - m) for x in samples]
    mad = median(deviations)
    if mad == 0:
        return None
    # 1.4826 is the constant that makes MAD comparable to standard deviation
    return (value - m) / (1.4826 * mad)


def _percentile(value: float, samples: List[float]) -> float | None:
    """Return percentile (0-100) of value within a sample distribution.

    This is used both for within-team distributions and global (all teams)
    distributions for the same metric.
    """

    if not samples:
        return None
    all_vals = sorted(samples + [value])
    # Use the last index where value appears to bias slightly toward the tail
    # for extreme values.
    idx = max(i for i, v in enumerate(all_vals) if v == value)
    n = len(all_vals)
    return 100.0 * (idx + 1) / n


def _format_insight(
    key: str,
    value: float,
    z: float,
    samples: List[float],
    team_percentile: float | None,
    league_percentile: float | None,
) -> str:
    # Turn a feature + z-score into a human-readable insight sentence.
    m = median(samples) if samples else value
    p_txt = ""
    if team_percentile is not None:
        p_rounded = max(1, min(99, int(round(team_percentile))))
        p_txt = f"; team-percentile {p_rounded}"
    if league_percentile is not None:
        lp_rounded = max(1, min(99, int(round(league_percentile))))
        p_txt = (p_txt + f"; league-percentile {lp_rounded}").lstrip("; ")

    if key.startswith("ppp:"):
        _metric, view, team = key.split(":", 2)
        direction = "above" if z > 0 else "below"
        return (
            f"AUTO: {team} points per possession in {view} view was {direction} its season median "
            f"({value:.2f} vs {m:.2f}; z-score {z:.1f}{p_txt})."
        )

    if key.startswith("fg3_share:"):
        _metric, _view, team = key.split(":", 2)
        direction = "above" if z > 0 else "below"
        return (
            f"AUTO: {team} 3-point make share was {direction} its season median "
            f"({value*100:.1f}% vs {m*100:.1f}%; z-score {z:.1f}{p_txt})."
        )

    if key.startswith("to_rate:"):
        _metric, _view, team = key.split(":", 2)
        direction = "above" if z > 0 else "below"
        return (
            f"AUTO: {team} turnover rate was {direction} its season median "
            f"({value*100:.1f}% vs {m*100:.1f}%; z-score {z:.1f}{p_txt})."
        )

    if key.startswith("oreb_points_share:"):
        _metric, _view, team = key.split(":", 2)
        direction = "above" if z > 0 else "below"
        return (
            f"AUTO: {team} scoring share from offensive rebounds was {direction} its season median "
            f"({value*100:.1f}% vs {m*100:.1f}%; z-score {z:.1f}{p_txt})."
        )

    # Fallback: generic phrasing for any future feature families.
    direction = "above" if z > 0 else "below"
    return f"AUTO: Feature {key} was {direction} season baseline (value {value:.3f}, median {m:.3f}, z-score {z:.1f}{p_txt})."


def run_auto_insights_for_game(game_path: str, seasoncode: str, data_dir: str, z_threshold: float = 1.5) -> Path:
    """Run automatic insights for a single game JSON.

    This function is intentionally self-contained: callers provide a target
    game file, the season code, and a directory containing other JSON files
    for the same season. The engine discovers features and anomalies on its
    own and writes an enriched sibling JSON file.
    """

    target_path = Path(game_path).resolve()
    base_dir = Path(data_dir).resolve()

    # Load target game and extract its features.
    target_game = _load_json(target_path)
    target_feats = _collect_features(target_game)

    # Build season-level baselines for each feature key using other games.
    baseline_team: Dict[str, List[float]] = {}
    baseline_global: Dict[str, List[float]] = {}
    pattern = f"multi_drilldown_real_data_{seasoncode}_"

    for candidate in base_dir.glob("multi_drilldown_real_data_*.json"):
        # Only consider games for the same season so distributions are apples-to-apples.
        if pattern not in candidate.name:
            continue
        # Skip the target game file itself when computing the baseline.
        if candidate.resolve() == target_path:
            continue
        game = _load_json(candidate)
        for feat in _collect_features(game):
            # Within-team baseline uses the full key (metric:view:team).
            baseline_team.setdefault(feat.key, []).append(feat.value)
            # Global baseline collapses across teams for the same metric+view.
            try:
                metric, view, _team = feat.key.split(":", 2)
            except ValueError:
                continue
            gkey = f"{metric}:{view}"
            baseline_global.setdefault(gkey, []).append(feat.value)

    scored: List[tuple[FeatureStat, float, List[float], float | None, float | None]] = []

    for feat in target_feats:
        samples = baseline_team.get(feat.key) or []
        # Require a minimal baseline to avoid extremely unstable z-scores.
        if len(samples) < 3:
            continue
        z = _robust_zscore(feat.value, samples)
        if z is None:
            continue
        p_team = _percentile(feat.value, samples)

        league_samples: List[float] = []
        try:
            metric, view, _team = feat.key.split(":", 2)
            gkey = f"{metric}:{view}"
            league_samples = baseline_global.get(gkey) or []
        except ValueError:
            league_samples = []
        p_league = _percentile(feat.value, league_samples) if len(league_samples) >= 3 else None

        scored.append((feat, z, samples, p_team, p_league))

    # Sort by absolute z-score so we can highlight the strongest outliers
    # across all features.
    scored.sort(key=lambda x: abs(x[1]), reverse=True)

    insights_to_add: List[str] = []
    for feat, z, samples, p_team, p_league in scored:
        if abs(z) < z_threshold:
            # We only keep clearly non-trivial deviations to avoid noise.
            continue
        if len(insights_to_add) >= 9:
            break
        insights_to_add.append(_format_insight(feat.key, feat.value, z, samples, p_team, p_league))

    # If nothing noteworthy was found, we still want a breadcrumb in the UI
    # so it is clear the engine ran.
    if not insights_to_add:
        insights_to_add.append(
            "AUTO: No strong statistical anomalies detected across PPP, 3P share, turnover rate, or OREB scoring share compared to this season's baseline."
        )

    views = target_game.get("views") or {}
    top = views.get("top") or {}
    existing_insights = top.get("insights") or []
    if not isinstance(existing_insights, list):
        existing_insights = [str(existing_insights)]

    # Append new insights without dropping manually-authored ones.
    top["insights"] = existing_insights + insights_to_add
    views["top"] = top
    target_game["views"] = views

    # Write out a sibling file so we do not disturb the original demo JSON.
    output_path = target_path.with_name(target_path.stem + "_auto.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(target_game, f, ensure_ascii=False, indent=2)

    print(f"[auto_insights] Wrote enriched JSON to {output_path}")
    return output_path
