"""Unit tests for the ELO rating engine (elo.py)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from basket.elo import (
    DEFAULT_INITIAL,
    DEFAULT_K,
    _outcome_score,
    _parse_gamedate,
    compute_elo_for_season,
    expected_score,
    update_ratings,
)


# ---------------------------------------------------------------------------
# expected_score
# ---------------------------------------------------------------------------


class TestExpectedScore:
    def test_equal_ratings_returns_half(self) -> None:
        assert expected_score(1500, 1500) == pytest.approx(0.5)

    def test_higher_rating_favoured(self) -> None:
        ea = expected_score(1600, 1500)
        assert ea > 0.5

    def test_lower_rating_underdog(self) -> None:
        ea = expected_score(1400, 1500)
        assert ea < 0.5

    def test_symmetry(self) -> None:
        ea = expected_score(1600, 1400)
        eb = expected_score(1400, 1600)
        assert ea + eb == pytest.approx(1.0)

    def test_400_point_gap(self) -> None:
        # Classical ELO: 400-point gap → expected ≈ 0.909
        ea = expected_score(1900, 1500)
        assert ea == pytest.approx(10 / 11, rel=1e-4)


# ---------------------------------------------------------------------------
# update_ratings
# ---------------------------------------------------------------------------


class TestUpdateRatings:
    def test_winner_gains_loser_loses(self) -> None:
        a, b = update_ratings(1500, 1500, score_a=1.0)
        assert a > 1500
        assert b < 1500

    def test_total_rating_conserved(self) -> None:
        initial_sum = 1500 + 1500
        a, b = update_ratings(1500, 1500, score_a=1.0)
        assert a + b == pytest.approx(initial_sum, abs=0.01)

    def test_equal_match_draw_no_change(self) -> None:
        a, b = update_ratings(1500, 1500, score_a=0.5)
        assert a == pytest.approx(1500)
        assert b == pytest.approx(1500)

    def test_upset_larger_gain(self) -> None:
        # Underdog wins → larger gain than favourite winning
        # WHEN: UNDERDOG WINS: 1400 won vs 1600
        gain_upset, _ = update_ratings(1400, 1600, score_a=1.0, k=32)

        gain_expected, _ = update_ratings(1600, 1400, score_a=1.0, k=32)
        
        other_elo_gains = [update_ratings(1500, 1500, score_a=1.0, k=32)[0], update_ratings(1401, 1400, score_a=1.0, k=32)[0], update_ratings(1399, 1400, score_a=1.0, k=32)[0]]

        # gain_upset is from 1400 baseline, gain_expected from 1600 baseline
        diff_upset = gain_upset - 1400
        diff_expected = gain_expected - 1600
        # THEN rating gain is bigger compared all like 'equal elo' or eloA > eloB
        assert diff_upset > diff_expected
        
        assert all([diff_upset > (g - 1500) for g in other_elo_gains])

    def test_k_factor_scales_change(self) -> None:
        a16, _ = update_ratings(1500, 1500, score_a=1.0, k=16)
        a32, _ = update_ratings(1500, 1500, score_a=1.0, k=32)
        assert (a32 - 1500) == pytest.approx(2 * (a16 - 1500), rel=1e-4)


# ---------------------------------------------------------------------------
# _outcome_score
# ---------------------------------------------------------------------------


class TestOutcomeScore:
    def test_winner_team_a(self) -> None:
        assert _outcome_score("Alpha", "Alpha", "Beta", None, None) == 1.0

    def test_winner_team_b(self) -> None:
        assert _outcome_score("Beta", "Alpha", "Beta", None, None) == 0.0

    def test_no_winner_uses_scores_a_wins(self) -> None:
        assert _outcome_score(None, "Alpha", "Beta", 85, 78) == 1.0

    def test_no_winner_uses_scores_b_wins(self) -> None:
        assert _outcome_score(None, "Alpha", "Beta", 70, 80) == 0.0

    def test_no_winner_draw(self) -> None:
        assert _outcome_score(None, "Alpha", "Beta", 75, 75) == 0.5

    def test_winner_unrelated_team_returns_none(self) -> None:
        # winner value doesn't match either team → treat as unknown
        assert _outcome_score("Unknown", "Alpha", "Beta", None, None) is None




# ---------------------------------------------------------------------------
# _parse_gamedate
# ---------------------------------------------------------------------------


class TestParseGamedate:
    def test_iso_string(self) -> None:
        assert _parse_gamedate("2024-03-15T20:00:00Z") == "2024-03-15"

    def test_date_only(self) -> None:
        assert _parse_gamedate("2024-03-15") == "2024-03-15"

    def test_none_returns_empty(self) -> None:
        assert _parse_gamedate(None) == ""

    def test_empty_returns_empty(self) -> None:
        assert _parse_gamedate("") == ""


# ---------------------------------------------------------------------------
# compute_elo_for_season (integration — uses temp directory)
# ---------------------------------------------------------------------------


def _write_game(
    out_dir: Path,
    seasoncode: str,
    gamecode: int,
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    gamedate: str,
) -> None:
    winner = team_a if score_a > score_b else (team_b if score_b > score_a else None)
    payload = {
        "meta": {
            "seasoncode": seasoncode,
            "gamecode": gamecode,
            "team_a": team_a,
            "team_b": team_b,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "gamedate": gamedate,
        }
    }
    fname = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
    (out_dir / fname).write_text(json.dumps(payload), encoding="utf-8")


class TestComputeEloForSeason:
    def test_output_file_written(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Beta", 85, 78, "2024-01-01")
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert (tmp_path / "elo_ETEST.json").exists()
        assert result["seasoncode"] == "ETEST"

    def test_ratings_keys_are_teams(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Beta", 85, 78, "2024-01-01")
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert "Alpha" in result["ratings"]
        assert "Beta" in result["ratings"]

    def test_winner_gains_rating(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Beta", 90, 70, "2024-01-01")
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert result["ratings"]["Alpha"] > DEFAULT_INITIAL
        assert result["ratings"]["Beta"] < DEFAULT_INITIAL

    def test_history_length(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Beta", 85, 78, "2024-01-01")
        _write_game(tmp_path, "ETEST", 2, "Alpha", "Gamma", 70, 80, "2024-01-05")
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert len(result["history"]) == 2

    def test_history_sorted_by_date(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 2, "Alpha", "Beta", 85, 78, "2024-01-05")
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Gamma", 70, 80, "2024-01-01")
        result = compute_elo_for_season(tmp_path, "ETEST")
        dates = [h["gamedate"] for h in result["history"]]
        assert dates == sorted(dates)

    def test_outcome_unknown_game_flagged(self, tmp_path: Path) -> None:
        payload = {
            "meta": {
                "seasoncode": "ETEST",
                "gamecode": 1,
                "team_a": "Alpha",
                "team_b": "Beta",
                "score_a": None,
                "score_b": None,
                "winner": None,
                "gamedate": "2024-01-01",
            }
        }
        (tmp_path / "multi_drilldown_real_data_ETEST_1.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert result["history"][0].get("outcome_unknown") is True
        # Ratings should remain at initial value (no update)
        assert result["ratings"].get("Alpha", DEFAULT_INITIAL) == DEFAULT_INITIAL
        assert result["ratings"].get("Beta", DEFAULT_INITIAL) == DEFAULT_INITIAL

    def test_custom_k_factor(self, tmp_path: Path) -> None:
        _write_game(tmp_path, "ETEST", 1, "Alpha", "Beta", 90, 70, "2024-01-01")
        result_k16 = compute_elo_for_season(tmp_path, "ETEST", k_factor=16)
        # Delete cached file and recompute
        (tmp_path / "elo_ETEST.json").unlink()
        result_k32 = compute_elo_for_season(tmp_path, "ETEST", k_factor=32)
        change_k16 = abs(result_k16["ratings"]["Alpha"] - DEFAULT_INITIAL)
        change_k32 = abs(result_k32["ratings"]["Alpha"] - DEFAULT_INITIAL)
        assert change_k32 == pytest.approx(2 * change_k16, rel=1e-4)

    def test_empty_dir_produces_empty_history(self, tmp_path: Path) -> None:
        result = compute_elo_for_season(tmp_path, "ETEST")
        assert result["history"] == []
        assert result["ratings"] == {}
