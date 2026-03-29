from __future__ import annotations

import pytest

from build_from_euroleague_api import run_game


SAMPLE_GAMES = [
    ("E2021", 54),
    ("E2021", 55),
]


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_basic_structure(seasoncode: str, gamecode: int) -> None:
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")

    # Top-level shape
    assert isinstance(payload, dict)
    assert "meta" in payload
    assert "colors" in payload
    assert "views" in payload

    meta = payload["meta"]
    views = payload["views"]

    # Meta sanity
    assert meta.get("seasoncode") == seasoncode
    assert meta.get("gamecode") == gamecode
    assert isinstance(meta.get("team_a"), str) and meta["team_a"]
    assert isinstance(meta.get("team_b"), str) and meta["team_b"]
    # Optional but useful metadata
    assert "synced_at" in meta

    # Views we expect to exist
    for key in ["top", "halfcourt", "transition", "oreb", "made2", "made3"]:
        assert key in views
        v = views[key]
        assert isinstance(v.get("nodes"), list) and v["nodes"]
        assert isinstance(v.get("links"), list) and v["links"]


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_top_view_has_made_shots(seasoncode: str, gamecode: int) -> None:
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")
    top = payload["views"]["top"]

    nodes = top["nodes"]
    links = top["links"]

    # Ensure we actually created event nodes for Made 2 / Made 3.
    event_names = {n["name"] for n in nodes if n.get("stage") == "event"}
    assert "Made 2" in event_names
    assert "Made 3" in event_names

    # Sanity: there should be some non-zero flows into 2- and 3-point buckets.
    has_two = any(str(l.get("target", "")).endswith("_2") and int(l.get("value", 0)) > 0 for l in links)
    has_three = any(str(l.get("target", "")).endswith("_3") and int(l.get("value", 0)) > 0 for l in links)
    assert has_two or has_three


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_halfcourt_subtypes_present(seasoncode: str, gamecode: int) -> None:
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")
    half = payload["views"]["halfcourt"]

    type_nodes = [n for n in half["nodes"] if n.get("stage") == "type"]
    names = {n["name"] for n in type_nodes}

    # We expect at least our main buckets to appear across sample games.
    expected_any = {"PnR / handler action", "Spot-up / swing", "Post / interior touch"}
    assert names & expected_any


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_transition_and_oreb_subtypes_present(seasoncode: str, gamecode: int) -> None:
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")
    transition = payload["views"]["transition"]
    oreb = payload["views"]["oreb"]

    trans_types = {n["name"] for n in transition["nodes"] if n.get("stage") == "type"}
    oreb_types = {n["name"] for n in oreb["nodes"] if n.get("stage") == "type"}

    # Transition heuristic labels
    assert trans_types & {"After defensive rebound", "Early offense flow"}

    # OREB heuristic labels
    assert oreb_types & {"Immediate putback", "Kick-out perimeter", "Reset half-court"}


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_expected_value_stats_present(seasoncode: str, gamecode: int) -> None:
    """Every view must expose a 'stats' section with per-team E[s] family."""
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")

    meta = payload["meta"]
    team_a = meta["team_a"]
    team_b = meta["team_b"]

    for view_key in ["top", "halfcourt", "transition", "oreb", "made2", "made3"]:
        view = payload["views"][view_key]
        assert "stats" in view, f"view '{view_key}' missing 'stats' key"
        stats = view["stats"]
        assert isinstance(stats, dict), f"view '{view_key}' stats should be a dict"

        for team in [team_a, team_b]:
            if team not in stats:
                # A sub-view may have no possessions for a team; that is OK.
                continue
            ts = stats[team]
            # Required scalar keys
            assert "E_s" in ts
            assert "possessions" in ts
            assert "attempts_2pt" in ts
            assert "attempts_3pt" in ts
            assert "ft_possessions" in ts
            # E_s must be a non-negative float
            assert isinstance(ts["E_s"], float)
            assert ts["E_s"] >= 0.0
            # Optional keys present but may be None
            assert "E_s2" in ts
            assert "E_s3" in ts
            assert "E_s1" in ts
            # When not None, expected values must be in plausible basketball ranges
            if ts["E_s2"] is not None:
                assert 0.0 <= ts["E_s2"] <= 2.0, f"E_s2 out of range: {ts['E_s2']}"
            if ts["E_s3"] is not None:
                assert 0.0 <= ts["E_s3"] <= 3.0, f"E_s3 out of range: {ts['E_s3']}"
            if ts["E_s1"] is not None:
                # E_s1 is FT pts / FT possessions; each FT event is tracked
                # individually (0 or 1 pt), so this is effectively FT% in [0, 1].
                assert 0.0 <= ts["E_s1"] <= 1.0, f"E_s1 out of range: {ts['E_s1']}"


@pytest.mark.parametrize("seasoncode, gamecode", SAMPLE_GAMES)
def test_expected_value_stats_top_kpis(seasoncode: str, gamecode: int) -> None:
    """Top view KPIs should include E[s2] / E[s3] / E[s1] entries when available."""
    payload = run_game(seasoncode, gamecode, f"_tmp_test_{seasoncode}_{gamecode}.json")
    top = payload["views"]["top"]

    kpi_labels = {row[0] for row in top["kpis"]}
    # Points-per-possession KPI must always be present (existing behaviour)
    meta = payload["meta"]
    assert any("points per poss" in label for label in kpi_labels)
    # When 2pt/3pt attempts exist the corresponding E[s] KPIs must appear
    stats = top.get("stats", {})
    for team in [meta["team_a"], meta["team_b"]]:
        ts = stats.get(team, {})
        if ts.get("E_s2") is not None:
            assert any(f"{team} E[s2]" in label for label in kpi_labels), \
                f"Missing E[s2] KPI for {team}"
        if ts.get("E_s3") is not None:
            assert any(f"{team} E[s3]" in label for label in kpi_labels), \
                f"Missing E[s3] KPI for {team}"
