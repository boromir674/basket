from __future__ import annotations

import argparse
import sys
from pathlib import Path
import os

from pipeline_runner import main as run_pipeline_main
from validate_output import validate_file
from season_sync import build_manifest
from season_ops import build_season_report, normalize_season_data_files


def run_pipeline_and_validate(argv: list[str]) -> int:
    """Run the pipeline (single or batch) and then validate outputs.

    This wires the two steps into a single command so Docker can expose a
    convenient one-liner.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--seasoncode", required=True)
    parser.add_argument(
        "--gamecode",
        action="append",
        required=True,
        help="Game code(s) to process; can be repeated or comma-separated",
    )
    parser.add_argument(
        "--output-pattern",
        default="multi_drilldown_real_data_{seasoncode}_{gamecode}.json",
    )
    parser.add_argument(
        "--output-dir", default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed")

    # We delegate the heavy lifting to pipeline_runner by reusing its CLI
    # contract, then run validation on the files it is expected to emit.
    args, _rest = parser.parse_known_args(argv)

    # First, run the pipeline using pipeline_runner's CLI entrypoint.
    run_args = [
        "--seasoncode",
        args.seasoncode,
    ]
    for gc in args.gamecode:
        run_args.extend(["--gamecode", gc])
    run_args.extend(["--output-pattern", args.output_pattern, "--output-dir", args.output_dir])

    print("=== Running pipeline ===")
    run_pipeline_main(run_args)

    # Now, construct expected output paths and validate them.
    expected_files: list[Path] = []
    from pipeline_runner import parse_gamecodes  # local import to avoid cycles

    gamecodes = parse_gamecodes(args.gamecode)
    out_dir = Path(args.output_dir).resolve()
    for gc in gamecodes:
        name = args.output_pattern.format(seasoncode=args.seasoncode, gamecode=gc)
        expected_files.append(out_dir / name)

    print("=== Validating outputs ===")
    any_failed = False
    for path in expected_files:
        is_valid, message = validate_file(path)
        status = "OK" if is_valid else "FAIL"
        print(f"[{status}] {path}: {message}")
        if not is_valid:
            any_failed = True

    if not any_failed:
        # Refresh manifest for this season so the game switcher UI knows about
        # newly generated JSON files.
        out_dir = Path(args.output_dir).resolve()
        build_manifest(out_dir, args.seasoncode)

    return 1 if any_failed else 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage:")
        print("  entrypoint.py run_pipeline_and_validate [ARGS...]")
        print("  entrypoint.py demo")
        print("  entrypoint.py demo_auto_insights")
        print("  entrypoint.py sync_season --seasoncode E2025 --start-gamecode 1 --end-gamecode 200 --output-dir data [--log-level DEBUG]")
        print("  entrypoint.py normalize_season_data --seasoncode E2025 --data-dir data [--dry-run]")
        print("  entrypoint.py report_season --seasoncode E2025 --data-dir data")
        print("  entrypoint.py prepare_season --seasoncode E2025 --start-gamecode 1 --end-gamecode 200 --data-dir data")
        print("  entrypoint.py compute_elo --seasoncode E2021 [--output-dir assets/processed] [--k-factor 32] [--initial-rating 1500]")
        print("  entrypoint.py rebuild_manifest --seasoncode E2021 [--output-dir assets/processed]")
        print()
        print("Examples:")
        print("  run_pipeline_and_validate --seasoncode E2021 --gamecode 54")
        print("  demo  # run a small pre-wired batch and validate")
        return 0

    command, *rest = argv

    if command == "run_pipeline_and_validate":
        return run_pipeline_and_validate(rest)

    if command == "demo":
        # Minimal curated set for quick exploration.
        # We hardcode a couple of games and also drop the last one
        # into multi_drilldown_real_data.json so the HTML can pick it
        # up without any edits.
        from build_from_euroleague_api import run_game

        scenarios = [("E2021", 54), ("E2021", 55)]
        out_dir = Path(os.getenv("BASKET_APP_FILE_STORE_URI", "assets")).resolve() / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)
        print("=== Demo run: generating sample games ===")
        last_path: Path | None = None
        for seasoncode, gamecode in scenarios:
            name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            path = out_dir / name
            print(f"  - {seasoncode} / {gamecode} -> {path}")
            run_game(seasoncode, gamecode, str(path))
            last_path = path

        if last_path is not None:
            # Also copy the last game into the viewer filename.
            viewer = out_dir / "multi_drilldown_real_data.json"
            viewer.write_text(last_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Viewer JSON updated: {viewer}")

        # Validate all generated files.
        print("=== Validating demo outputs ===")
        any_failed = False
        for seasoncode, gamecode in scenarios:
            name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            path = out_dir / name
            is_valid, message = validate_file(path)
            status = "OK" if is_valid else "FAIL"
            print(f"[{status}] {path}: {message}")
            if not is_valid:
                any_failed = True

        if not any_failed:
            # Refresh manifest for this season so the game switcher can list
            # the demo games without running season_sync separately.
            build_manifest(out_dir, "E2021")

        return 1 if any_failed else 0

    if command == "demo_auto_insights":
        # Experimental path: generate a single demo game (E2021 / 54) if needed
        # and then run the automatic insights engine against it, producing a
        # sibling JSON file that the UI can point at.
        from build_from_euroleague_api import run_game
        from auto_insights import run_auto_insights_for_game

        seasoncode = "E2021"
        gamecode = 54
        out_dir = Path(os.getenv("BASKET_APP_FILE_STORE_URI", "assets")).resolve() / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Ensure the base JSON for this game exists so the engine has
        # something to work with.
        game_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        game_path = out_dir / game_name
        if not game_path.exists():
            print("=== Demo auto-insights: generating base game ===")
            run_game(seasoncode, gamecode, str(game_path))

        print("=== Validating base game for auto-insights ===")
        is_valid, message = validate_file(game_path)
        status = "OK" if is_valid else "FAIL"
        print(f"[{status}] {game_path}: {message}")
        if not is_valid:
            return 1

        # Run the engine using all other season files as the baseline.
        print("=== Running automatic insights engine ===")
        run_auto_insights_for_game(str(game_path), seasoncode, str(out_dir))
        return 0

    if command == "compute_elo":
        from elo import main as elo_main

        return elo_main(rest)

    if command == "sync_season":
        # Wrapper around season_sync so we keep a single top-level entrypoint.
        from season_sync import main as season_sync_main

        return season_sync_main(rest)

    if command == "normalize_season_data":
        parser = argparse.ArgumentParser(description="Normalize/canonicalize stored season JSON files in-place.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing season JSON files (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        counts = normalize_season_data_files(seasoncode=args.seasoncode, data_dir=data_dir, dry_run=args.dry_run)
        mode = "DRY-RUN" if args.dry_run else "LIVE"
        print(f"=== normalize_season_data ({mode}) {args.seasoncode} in {data_dir} ===")
        print(f"files_total={counts['files_total']}, files_changed={counts['files_changed']}")

        if not args.dry_run:
            # Keep the UI game switcher consistent with any rewritten team labels.
            build_manifest(data_dir, args.seasoncode)
            print("manifest_rebuilt=1")
        return 0

    if command == "report_season":
        parser = argparse.ArgumentParser(description="Report season data quality stats from stored JSON files.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing season JSON files (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        args = parser.parse_args(rest)

        report = build_season_report(seasoncode=args.seasoncode, data_dir=Path(args.data_dir).resolve())
        print(f"=== Season report: {report.seasoncode} ===")
        print(f"games={report.games}")
        print(f"distinct_teams={report.distinct_teams}")
        print("teams=")
        for t in report.teams:
            print(f"  - {t}")
        return 0

    if command == "prepare_season":
        # One-shot helper: sync -> normalize -> compute elo -> rebuild manifest -> report.
        parser = argparse.ArgumentParser(description="Prepare a season end-to-end (sync + normalize + elo + report).")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument("--start-gamecode", type=int, default=1)
        parser.add_argument("--end-gamecode", type=int, default=200)
        parser.add_argument(
            "--data-dir",
            default="data",
            help="Directory where season JSONs live (and outputs are written). Default: data",
        )
        parser.add_argument("--max-failures", type=int, default=25)
        parser.add_argument("--force", action="store_true")
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)

        from season_sync import main as season_sync_main
        from elo import main as elo_main

        print("=== [1/5] Sync season ===")
        season_sync_main(
            [
                "--seasoncode",
                args.seasoncode,
                "--start-gamecode",
                str(args.start_gamecode),
                "--end-gamecode",
                str(args.end_gamecode),
                "--output-dir",
                str(data_dir),
                "--max-failures",
                str(args.max_failures),
            ]
            + (["--force"] if args.force else [])
        )

        print("=== [2/5] Normalize stored JSONs ===")
        normalize_season_data_files(seasoncode=args.seasoncode, data_dir=data_dir, dry_run=False)

        print("=== [3/5] Compute Elo ===")
        elo_main(["--seasoncode", args.seasoncode, "--output-dir", str(data_dir)])

        print("=== [4/5] Rebuild manifest (includes Elo badges) ===")
        build_manifest(data_dir, args.seasoncode)

        print("=== [5/5] Report ===")
        report = build_season_report(seasoncode=args.seasoncode, data_dir=data_dir)
        print(f"games={report.games}")
        print(f"distinct_teams={report.distinct_teams}")
        return 0

    if command == "rebuild_manifest":
        parser = argparse.ArgumentParser(description="Rebuild games_manifest.json from existing JSON files.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2021")
        parser.add_argument(
            "--output-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory where JSON files live (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        args = parser.parse_args(rest)

        out_dir = Path(args.output_dir).resolve()
        print(f"=== Rebuilding manifest for {args.seasoncode} in {out_dir} ===")
        build_manifest(out_dir, args.seasoncode)
        return 0

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
