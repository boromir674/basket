import json
from pathlib import Path


def test_season_2025_distinct_teams_is_20() -> None:
    # GIVEN a season (ie 2025)
    seasoncode = "E2025"
    expected_teams = 20
    # Double round-robin: each pair plays twice => n*(n-1) total games
    expected_games = expected_teams * (expected_teams - 1)  # 380

    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"

    # WHEN we examine the "database games" (ie JSON files)
    game_files = sorted(data_dir.glob(f"multi_drilldown_real_data_{seasoncode}_*.json"))

    assert game_files, (
        "No season game JSON files found. "
        f"Expected files like {data_dir}/multi_drilldown_real_data_{seasoncode}_*.json"
    )

    # THEN all files for the season are present (round-robin completeness)
    assert len(game_files) == expected_games, (
        f"Expected {expected_games} game JSON files for {seasoncode} (20-team double round-robin), "
        f"got {len(game_files)}."
    )

    teams: set[str] = set()
    for path in game_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}

        team_a = meta.get("team_a")
        team_b = meta.get("team_b")

        if isinstance(team_a, str) and team_a.strip():
            teams.add(team_a.strip())
        if isinstance(team_b, str) and team_b.strip():
            teams.add(team_b.strip())

    # THEN number of distinct participating teams EXPECTED as 20
    assert len(teams) == expected_teams, (
        f"Expected {expected_teams} distinct teams for {seasoncode}, got {len(teams)}. "
        f"Teams={sorted(teams)}"
    )
