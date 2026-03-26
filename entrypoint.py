from __future__ import annotations

import argparse
import sys
from pathlib import Path
import os

from pipeline_runner import main as run_pipeline_main
from validate_output import validate_file
from season_sync import build_manifest


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
        print("  entrypoint.py rebuild_manifest --seasoncode E2021 [--output-dir .]")
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
        out_dir = Path(".").resolve()
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
        out_dir = Path(".").resolve()

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

    if command == "rebuild_manifest":
        parser = argparse.ArgumentParser(description="Rebuild games_manifest.json from existing JSON files.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2021")
        parser.add_argument(
            "--output-dir",
            default=".",
            help="Directory where JSON files live (default: current directory)",
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
