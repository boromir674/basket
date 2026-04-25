from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture()
def season_sync_mod():
    import season_sync

    return season_sync


def test_verify_season_ingestion_process_reports_expected_information_single_game(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    season_sync_mod,
) -> None:
    # GIVEN mocked season-ingestion internals so no external API/network call is executed.
    calls = {"count": 0}

    def _fake_build_one_game(*, seasoncode: str, gamecode: int, out_path: Path):
        calls["count"] += 1
        if gamecode == 1:
            return (
                True,
                {
                    "seasoncode": seasoncode,
                    "gamecode": gamecode,
                    "gamedate": "2022-10-01",
                },
                "",
                "",
            )
        return False, None, "transient", "mocked transient failure"

    manifest_calls: list[tuple[Path, str]] = []

    def _fake_build_manifest(output_dir: Path, seasoncode: str) -> None:
        manifest_calls.append((output_dir, seasoncode))

    monkeypatch.setattr(season_sync_mod, "_build_one_game", _fake_build_one_game)
    monkeypatch.setattr(season_sync_mod, "build_manifest", _fake_build_manifest)

    # WHEN running the season ingestion CLI flow for two gamecodes.
    exit_code = season_sync_mod.main(
        [
            "--seasoncode",
            "E2022",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "2",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )

    # THEN stdout/stderr should contain expected human-facing progress and summary logs.
    captured = capsys.readouterr()
    console_text = f"{captured.out}\n{captured.err}"

    assert exit_code == 0
    assert calls["count"] == 2

    expected_console_text = dedent(
        """
        [INFO] Starting season ingestion:
          seasoncode: E2022
          planned_games: 2

        [INFO] First successful game fetched:
          seasoncode: E2022
          gamecode:   1
          gamedate:   2022-10-01

        [INFO] Failure diagnostics:
          failures_total: 1
          stopped_early: no
          retriable_failures:
            - transient (network/timeout — safe to retry): 1
            - exception: mocked transient failure: 1
            - game=2 type=transient msg=mocked transient failure

        [INFO] Season ingestion summary:
          seasoncode: E2022
          downloaded_ok: 1/2
          failures: 1

        """
    )

    assert expected_console_text == console_text

    assert len(manifest_calls) == 1
    assert manifest_calls[0][1] == "E2022"


def test_verify_season_ingestion_process_reports_expected_information_two_seasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    season_sync_mod,
) -> None:
    # GIVEN mocked season-ingestion internals so no external API/network call is executed.
    calls = {"count": 0}
    fake_games = {
        ("E2022", 1): "2022-10-01",
        ("E2022", 2): "2022-10-03",
        ("E2022", 3): "2022-10-05",
        ("E2023", 1): "2023-10-02",
        ("E2023", 2): "2023-10-04",
    }

    def _fake_build_one_game(*, seasoncode: str, gamecode: int, out_path: Path):
        calls["count"] += 1
        gamedate = fake_games.get((seasoncode, gamecode))
        if gamedate is None:
            return False, None, "transient", "mocked transient failure"
        return (
            True,
            {
                "seasoncode": seasoncode,
                "gamecode": gamecode,
                "gamedate": gamedate,
            },
            "",
            "",
        )

    manifest_calls: list[tuple[Path, str]] = []

    def _fake_build_manifest(output_dir: Path, seasoncode: str) -> None:
        manifest_calls.append((output_dir, seasoncode))

    monkeypatch.setattr(season_sync_mod, "_build_one_game", _fake_build_one_game)
    monkeypatch.setattr(season_sync_mod, "build_manifest", _fake_build_manifest)

    # WHEN running the season ingestion CLI flow for two different seasons.
    exit_code_a = season_sync_mod.main(
        [
            "--seasoncode",
            "E2022",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "3",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )
    exit_code_b = season_sync_mod.main(
        [
            "--seasoncode",
            "E2023",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "2",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )

    # THEN stdout/stderr should contain one exact combined console output string.
    captured = capsys.readouterr()
    console_text = f"{captured.out}\n{captured.err}"

    assert exit_code_a == 0
    assert exit_code_b == 0
    assert calls["count"] == 5

    expected_console_text = dedent(
        """
        [INFO] Starting season ingestion:
          seasoncode: E2022
          planned_games: 3

        [INFO] First successful game fetched:
          seasoncode: E2022
          gamecode:   1
          gamedate:   2022-10-01

        [INFO] Season ingestion summary:
          seasoncode: E2022
          downloaded_ok: 3/3
          failures: 0

        [INFO] Starting season ingestion:
          seasoncode: E2023
          planned_games: 2

        [INFO] First successful game fetched:
          seasoncode: E2023
          gamecode:   1
          gamedate:   2023-10-02

        [INFO] Season ingestion summary:
          seasoncode: E2023
          downloaded_ok: 2/2
          failures: 0

        """
    )

    assert expected_console_text == console_text

    assert len(manifest_calls) == 2
    assert manifest_calls[0][1] == "E2022"
    assert manifest_calls[1][1] == "E2023"


def test_verify_season_ingestion_process_reports_expected_information_previous_seasons_when_newer_season_already_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    season_sync_mod,
) -> None:
    # GIVEN mocked season-ingestion internals and pre-existing stored data for a newer season.
    calls = {"count": 0}
    fake_games = {
        ("E2023", 1): "2023-10-02",
        ("E2023", 2): "2023-10-04",
        ("E2022", 1): "2022-10-01",
        ("E2022", 2): "2022-10-03",
        ("E2022", 3): "2022-10-05",
    }

    existing_newer_season_file = tmp_path / "multi_drilldown_real_data_E2024_1.json"
    original_newer_season_payload = "{\n  \"meta\": {\n    \"seasoncode\": \"E2024\",\n    \"gamecode\": 1\n  }\n}\n"
    existing_newer_season_file.write_text(original_newer_season_payload, encoding="utf-8")

    def _fake_build_one_game(*, seasoncode: str, gamecode: int, out_path: Path):
        calls["count"] += 1
        gamedate = fake_games.get((seasoncode, gamecode))
        if gamedate is None:
            return False, None, "transient", "mocked transient failure"
        return (
            True,
            {
                "seasoncode": seasoncode,
                "gamecode": gamecode,
                "gamedate": gamedate,
            },
            "",
            "",
        )

    manifest_calls: list[tuple[Path, str]] = []

    def _fake_build_manifest(output_dir: Path, seasoncode: str) -> None:
        manifest_calls.append((output_dir, seasoncode))

    monkeypatch.setattr(season_sync_mod, "_build_one_game", _fake_build_one_game)
    monkeypatch.setattr(season_sync_mod, "build_manifest", _fake_build_manifest)

    # WHEN running ingestion for previous seasons while newer season data already exists.
    exit_code_a = season_sync_mod.main(
        [
            "--seasoncode",
            "E2023",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "2",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )
    exit_code_b = season_sync_mod.main(
        [
            "--seasoncode",
            "E2022",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "3",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )

    # THEN ingestion should succeed for both previous seasons and print the expected report.
    captured = capsys.readouterr()
    console_text = f"{captured.out}\n{captured.err}"

    assert exit_code_a == 0
    assert exit_code_b == 0
    assert calls["count"] == 5
    assert existing_newer_season_file.read_text(encoding="utf-8") == original_newer_season_payload

    expected_console_text = dedent(
        """
        [INFO] Starting season ingestion:
          seasoncode: E2023
          planned_games: 2

        [INFO] First successful game fetched:
          seasoncode: E2023
          gamecode:   1
          gamedate:   2023-10-02

        [INFO] Season ingestion summary:
          seasoncode: E2023
          downloaded_ok: 2/2
          failures: 0

        [INFO] Stored seasons inventory:
          E2024: games=1 earliest=n/a latest=n/a

        [INFO] Starting season ingestion:
          seasoncode: E2022
          planned_games: 3

        [INFO] First successful game fetched:
          seasoncode: E2022
          gamecode:   1
          gamedate:   2022-10-01

        [INFO] Season ingestion summary:
          seasoncode: E2022
          downloaded_ok: 3/3
          failures: 0

        [INFO] Stored seasons inventory:
          E2024: games=1 earliest=n/a latest=n/a

        """
    )

    assert expected_console_text == console_text

    assert len(manifest_calls) == 2
    assert manifest_calls[0][1] == "E2023"
    assert manifest_calls[1][1] == "E2022"


def test_verify_season_ingestion_process_reports_stored_seasons_inventory_after_sync_tdd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    season_sync_mod,
) -> None:
    # GIVEN an output directory that already contains multiple seasons plus new games to ingest.
    existing_payloads = {
        "multi_drilldown_real_data_E2022_11.json": {
            "meta": {"seasoncode": "E2022", "gamecode": 11, "gamedate": "2022-10-01"}
        },
        "multi_drilldown_real_data_E2022_12.json": {
            "meta": {"seasoncode": "E2022", "gamecode": 12, "gamedate": "2022-10-03"}
        },
        "multi_drilldown_real_data_E2024_21.json": {
            "meta": {"seasoncode": "E2024", "gamecode": 21, "gamedate": "2024-10-05"}
        },
        "multi_drilldown_real_data_E2024_22.json": {
            "meta": {"seasoncode": "E2024", "gamecode": 22, "gamedate": "2024-10-09"}
        },
        "multi_drilldown_real_data_E2024_23.json": {
            "meta": {"seasoncode": "E2024", "gamecode": 23, "gamedate": "2024-10-13"}
        },
    }
    for filename, payload in existing_payloads.items():
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")

    calls = {"count": 0}
    fake_new_games = {
        ("E2023", 1): "2023-10-02",
        ("E2023", 2): "2023-10-04",
    }

    def _fake_build_one_game(*, seasoncode: str, gamecode: int, out_path: Path):
        calls["count"] += 1
        gamedate = fake_new_games.get((seasoncode, gamecode))
        if gamedate is None:
            return False, None, "transient", "mocked transient failure"
        out_path.write_text(
            dedent(
                f"""
                {{
                  "meta": {{
                    "seasoncode": "{seasoncode}",
                    "gamecode": {gamecode},
                    "gamedate": "{gamedate}"
                  }}
                }}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return (
            True,
            {
                "seasoncode": seasoncode,
                "gamecode": gamecode,
                "gamedate": gamedate,
            },
            "",
            "",
        )

    monkeypatch.setattr(season_sync_mod, "_build_one_game", _fake_build_one_game)
    monkeypatch.setattr(season_sync_mod, "build_manifest", lambda output_dir, seasoncode: None)

    # WHEN running ingestion for E2023 season.
    exit_code = season_sync_mod.main(
        [
            "--seasoncode",
            "E2023",
            "--start-gamecode",
            "1",
            "--end-gamecode",
            "2",
            "--output-dir",
            str(tmp_path),
            "--max-failures",
            "5",
            "--concurrency",
            "1",
            "--log-level",
            "CRITICAL",
        ]
    )

    # THEN console report should include a high-level stored-seasons inventory summary.
    captured = capsys.readouterr()
    console_text = f"{captured.out}\n{captured.err}"

    assert exit_code == 0
    assert calls["count"] == 2

    expected_console_text = dedent(
        """
        [INFO] Starting season ingestion:
          seasoncode: E2023
          planned_games: 2

        [INFO] First successful game fetched:
          seasoncode: E2023
          gamecode:   1
          gamedate:   2023-10-02

        [INFO] Season ingestion summary:
          seasoncode: E2023
          downloaded_ok: 2/2
          failures: 0

        [INFO] Stored seasons inventory:
          E2022: games=2 earliest=2022-10-01 latest=2022-10-03
          E2023: games=2 earliest=2023-10-02 latest=2023-10-04
          E2024: games=3 earliest=2024-10-05 latest=2024-10-13

        """
    )

    assert expected_console_text == console_text


def test_verify_dedicated_entry_point_reports_stored_seasons_inventory_tdd(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # GIVEN stored season data already available in output directory.
    import entrypoint

    existing_payloads = {
        "multi_drilldown_real_data_E2021_51.json": {
            "meta": {"seasoncode": "E2021", "gamecode": 51, "gamedate": "2021-10-01"}
        },
        "multi_drilldown_real_data_E2021_52.json": {
            "meta": {"seasoncode": "E2021", "gamecode": 52, "gamedate": "2021-10-05"}
        },
        "multi_drilldown_real_data_E2023_10.json": {
            "meta": {"seasoncode": "E2023", "gamecode": 10, "gamedate": "2023-10-09"}
        },
    }
    for filename, payload in existing_payloads.items():
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")

    # WHEN running dedicated inventory entry point.
    exit_code = entrypoint.main(
        [
            "report_inventory",
            "--output-dir",
            str(tmp_path),
        ]
    )

    # THEN inventory-only report should be printed with season-level aggregation.
    captured = capsys.readouterr()
    console_text = f"{captured.out}\n{captured.err}"

    assert exit_code == 0

    expected_console_text = dedent(
        """
        [INFO] Stored seasons inventory:
          E2021: games=2 earliest=2021-10-01 latest=2021-10-05
          E2023: games=1 earliest=2023-10-09 latest=2023-10-09

        """
    )

    assert expected_console_text == console_text
