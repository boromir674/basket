from __future__ import annotations

from basket.elo import DEFAULT_INITIAL, compute_elo_from_games


def test_elo_round_robin_most_wins_ends_highest_elo() -> None:
    # GIVEN a tiny 4-team league playing a double round-robin (each pair plays twice)
    # and one clearly dominant team (A) plus one clearly weak team (D)
    teams = ["A", "B", "C", "D"]

    # We define outcomes only (winner), because Elo cares about W/L here.
    # Note: chronological order matters in Elo, so we keep a deterministic schedule.
    games: list[dict[str, object]] = []
    gamecode = 1

    def add_game(team_a: str, team_b: str, winner: str) -> None:
        nonlocal gamecode
        games.append(
            {
                "gamecode": gamecode,
                "gamedate": f"2025-01-{gamecode:02d}",
                "team_a": team_a,
                "team_b": team_b,
                "winner": winner,
                # scores omitted on purpose; winner is the primary signal
            }
        )
        gamecode += 1

    # A beats everyone twice (6-0)
    add_game("A", "B", winner="A")
    add_game("B", "A", winner="A")
    add_game("A", "C", winner="A")
    add_game("C", "A", winner="A")
    add_game("A", "D", winner="A")
    add_game("D", "A", winner="A")

    # B beats C twice (2 wins) and D twice (2 wins) => B goes 4-2
    add_game("B", "C", winner="B")
    add_game("C", "B", winner="B")
    add_game("B", "D", winner="B")
    add_game("D", "B", winner="B")

    # C beats D twice => C goes 2-4
    add_game("C", "D", winner="C")
    add_game("D", "C", winner="C")

    # Sanity: all teams show up in schedule
    assert {g["team_a"] for g in games} | {g["team_b"] for g in games} == set(teams)

    # WHEN we compute Elo from the exact production Elo implementation (shared library)
    ratings, history = compute_elo_from_games(games, k_factor=32, initial_rating=DEFAULT_INITIAL)

    # THEN the dominant team should end with the highest Elo
    # and the winless team should end with the lowest Elo
    assert len(history) == len(games)
    assert max(ratings, key=ratings.get) == "A"
    assert min(ratings, key=ratings.get) == "D"

    # THEN the middle teams should be ordered by their win counts (B above C)
    assert ratings["B"] > ratings["C"]
