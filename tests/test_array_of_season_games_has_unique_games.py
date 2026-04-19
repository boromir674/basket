import json
from pathlib import Path

import pytest

from basket.clubs import normalize_team_name


@pytest.mark.parametrize(
    "seasoncode,file_prefix",
    [
        ("E2025", "multi_drilldown_real_data_E2025"),
    ],
)
def test_array_of_season_games_has_unique_games(seasoncode: str, file_prefix: str) -> None:
    """Ensure the season "DB" has no duplicate games.

    Important: in a double round-robin, the same matchup can happen multiple times.
    Also, the processed bundles do not currently carry an explicit home/away flag.
    Therefore, a pure "Team A vs Team B" key is NOT a safe game identity.

    We treat (seasoncode, gamecode) as the unique game identity.
    We still compute a normalized "Team A vs Team B" label for reporting.
    """

    # GIVEN the data file prefix for a season
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"

    # WHEN the test discovers files and reads them
    game_files = sorted(data_dir.glob(f"{file_prefix}_*.json"))
    assert game_files, (
        "No season game JSON files found. "
        f"Expected files like {data_dir}/{file_prefix}_*.json"
    )

    def filename_gamecode(path: Path) -> int | None:
        # Expected: ..._{gamecode}.json
        stem = path.stem
        parts = stem.split("_")
        if not parts:
            return None
        tail = parts[-1]
        try:
            return int(tail)
        except ValueError:
            return None

    # WHEN the test discovers files and reads them
    seen_ids: dict[tuple[str, int], str] = {}
    bad: list[str] = []

    for path in game_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            bad.append(f"{path} (root is not an object)")
            continue

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            bad.append(f"{path} (missing meta object)")
            continue

        sc = meta.get("seasoncode")
        gc = meta.get("gamecode")
        if sc != seasoncode:
            bad.append(f"{path} (meta.seasoncode={sc!r}, expected {seasoncode!r})")
            continue
        if not isinstance(gc, int):
            bad.append(f"{path} (meta.gamecode={gc!r} is not int)")
            continue

        # THEN file naming and meta agree (helps catch accidental copy/dup).
        gc_from_name = filename_gamecode(path)
        if gc_from_name is None:
            bad.append(f"{path} (cannot parse gamecode from filename)")
            continue
        if gc_from_name != gc:
            bad.append(f"{path} (filename gamecode={gc_from_name}, meta.gamecode={gc})")
            continue

        team_a = meta.get("team_a")
        team_b = meta.get("team_b")
        if isinstance(team_a, str) and team_a.strip() and isinstance(team_b, str) and team_b.strip():
            a = normalize_team_name(team_a).strip()
            b = normalize_team_name(team_b).strip()
            label = f"{a} vs {b}"  # order preserved; not used as identity.
        else:
            label = "(missing team_a/team_b)"

        game_id = (seasoncode, gc)
        if game_id in seen_ids:
            bad.append(
                "Duplicate game identity detected: "
                f"season={seasoncode} gamecode={gc} label={label}. "
                f"first={seen_ids[game_id]} dup={path}"
            )
        else:
            seen_ids[game_id] = str(path)

    assert not bad, (
        f"Season {seasoncode} DB uniqueness check failed.\n"
        + "\n".join([f"- {x}" for x in bad[:80]])
        + ("\n..." if len(bad) > 80 else "")
    )

    # THEN all discovered files map to distinct (seasoncode, gamecode)
    assert len(seen_ids) == len(game_files), (
        f"Expected {len(game_files)} unique (seasoncode,gamecode) ids, got {len(seen_ids)}."
    )
