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
