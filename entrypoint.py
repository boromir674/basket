from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
import os

from basket.clubs import DEFAULT_REGISTRY
from basket.elo import compute_elo_for_season, recompute_multiseason_elo_if_needed
from pipeline_runner import main as run_pipeline_main
from validate_output import validate_file
from season_sync import build_manifest, print_stored_seasons_inventory, main as season_sync_main
from style_insights import main as style_insights_main
from season_ops import (
    backfill_season_gamedates,
    build_season_report,
    find_unknown_club_names,
    normalize_season_data_files,
)


def orchestrate_full_season_sync(
    *,
    seasoncode: str,
    output_dir: Path,
    sync_fn,  # Injected season_sync main callable
    insights_fn,  # Injected style_insights main callable
) -> int:
    """Orchestrate full season pipeline: sync (raw + multi + score_timeline) + style_insights.

    Uses composition and dependency injection to keep sync and insights decoupled.
    Both remain standalone and testable; this orchestrator chains them.
    """
    print(f"\n=== Full Season Sync: {seasoncode} ===")

    # Step 1: season_sync (produces raw, multi, score_timeline)
    print(f"=== [1/2] Syncing season data (raw + multi + score_timeline) ===")
    sync_result = sync_fn(
        [
            "--seasoncode",
            seasoncode,
            "--output-dir",
            str(output_dir),
        ]
    )
    if sync_result != 0:
        print(f"ERROR: season_sync failed with code {sync_result}")
        return sync_result

    # Step 2: style_insights (produces style_insights_E####.json)
    print(f"=== [2/2] Building style insights (consistency + adaptability) ===")
    insights_result = insights_fn(
        [
            "--seasoncode",
            seasoncode,
            "--data-dir",
            str(output_dir),
            "--output-dir",
            str(output_dir),
        ]
    )
    if insights_result != 0:
        print(f"ERROR: style_insights failed with code {insights_result}")
        return insights_result

    print(f"\n✓ Full season sync complete: {seasoncode}")
    print(f"  Artifacts: raw_*, multi_*, score_timeline_*, style_insights_*")
    return 0


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
        print("  entrypoint.py sync_season_full --seasoncode E2025 --output-dir data [--log-level DEBUG]")
        print("  entrypoint.py redo_season --seasoncode E2025 [--data-dir /app/data] [--concurrency 16] [--dry-run]")
        print("  entrypoint.py sync_season --seasoncode E2025 --output-dir data [--log-level DEBUG]")
        print("  entrypoint.py normalize_season_data --seasoncode E2025 --data-dir data [--workers 8] [--dry-run]")
        print("  entrypoint.py normalize_all_seasons --data-dir data [--workers 8] [--dry-run]")
        print("  entrypoint.py backfill_gamedates --seasoncode E2025 --data-dir data --raw-dir assets [--dry-run]")
        print("  entrypoint.py report_season --seasoncode E2025 --data-dir data")
        print("  entrypoint.py report_inventory [--output-dir assets/processed]")
        print("  entrypoint.py prepare_season --seasoncode E2025 --data-dir data")
        print("  entrypoint.py compute_elo --seasoncode E2021 [--output-dir assets/processed] [--k-factor 32] [--initial-rating 1500]")
        print("  entrypoint.py compute_elo --seasoncodes E2022,E2023,E2024 [--output-dir assets/processed] [--output-name elo_multiseason.json]")
        print("  entrypoint.py compute_elo --auto [--output-dir assets/processed] [--output-name elo_multiseason.json] [--force]")
        print("  entrypoint.py rebuild_manifest --seasoncode E2021 [--output-dir assets/processed]")
        print("  entrypoint.py build_score_timeline [--seasoncode E2025] [--gamecode 54,55] [--raw-dir assets] [--output-dir data]")
        print("  entrypoint.py style_insights --seasoncode E2025 [--data-dir data] [--output-dir data]")
        print("  entrypoint.py check_dates [--data-dir /app/data] [--seasoncode E2025]")
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

    if command == "redo_season":
        parser = argparse.ArgumentParser(
            description="Delete all stored files for a season then re-fetch in a single API pass."
        )
        parser.add_argument("--seasoncode", required=True)
        parser.add_argument("--data-dir", default="/app/data")
        parser.add_argument("--raw-dir", default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets"))
        parser.add_argument("--concurrency", type=int, default=16)
        parser.add_argument("--gap-limit", type=int, default=10,
                            help="Stop after this many failures (single-pass stop condition)")
        parser.add_argument("--max-gamecode", type=int, default=999,
                            help="Upper gamecode bound for the single ingest pass")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report delete + ingest plan without changing files")
        args = parser.parse_args(rest)

        seasoncode = args.seasoncode
        data_dir = Path(args.data_dir).resolve()
        raw_dir = Path(args.raw_dir).resolve()

        print(f"=== redo_season {seasoncode} ===")
        print("Single-pass mode: no pre-probe API calls.")
        print(
            f"Going over season gamecodes from 1 upward (single pass, hard cap={args.max_gamecode}, stop after {args.gap_limit} failures)."
        )

        if args.dry_run:
            print("DRY-RUN: would delete season files and run one sync pass. Exiting.")
            return 0

        # Delete existing processed + raw files for this season.
        deleted = 0
        for pattern, directory in [
            (f"multi_drilldown_real_data_{seasoncode}_*.json", data_dir),
            (f"raw_pbp_{seasoncode}_*.json", raw_dir),
            (f"raw_pts_{seasoncode}_*.json", raw_dir),
            (f"raw_box_{seasoncode}_*.json", raw_dir),
        ]:
            for f in directory.glob(pattern):
                f.unlink()
                deleted += 1
        print(f"Deleted {deleted} existing files for {seasoncode}.")

        # Re-sync over the discovered range (all gaps handled by permanent-skip logic).
        os.environ["BASKET_APP_FILE_STORE_URI"] = str(raw_dir)
        sync_args = [
            "--seasoncode", seasoncode,
            "--output-dir", str(data_dir),
            "--concurrency", str(args.concurrency),
            "--max-failures", str(args.gap_limit),
            "--retry-pass",
            "--log-level", "INFO",
        ]
        return season_sync_main(sync_args)

    if command == "sync_season_full":
        # Orchestrate full season sync: raw + multi + score_timeline + style_insights.
        # Demonstrates composition and dependency injection for clean decoupling.
        parser = argparse.ArgumentParser(
            description="Full season sync: orchestrates season_sync + style_insights in sequence."
        )
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument(
            "--output-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory for all outputs (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        args = parser.parse_args(rest)
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Inject both sync and insights functions as dependencies
        return orchestrate_full_season_sync(
            seasoncode=args.seasoncode,
            output_dir=output_dir,
            sync_fn=season_sync_main,
            insights_fn=style_insights_main,
        )

    if command == "sync_season":
        # Wrapper around season_sync so we keep a single top-level entrypoint.
        return season_sync_main(rest)

    if command == "normalize_season_data":
        parser = argparse.ArgumentParser(description="Normalize/canonicalize stored season JSON files in-place.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing season JSON files (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=max(1, min(16, os.cpu_count() or 1)),
            help="Thread workers for concurrent file I/O (default: min(16, CPU count))",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
        parser.add_argument(
            "--skip-elo-refresh",
            action="store_true",
            help="Skip recomputing ELO payloads after normalization",
        )
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        counts = normalize_season_data_files(
            seasoncode=args.seasoncode,
            data_dir=data_dir,
            dry_run=args.dry_run,
            workers=args.workers,
        )
        mode = "DRY-RUN" if args.dry_run else "LIVE"
        print(f"=== normalize_season_data ({mode}) {args.seasoncode} in {data_dir} ===")
        print(f"files_total={counts['files_total']}, files_changed={counts['files_changed']}")
        aliases = counts.get("normalized_aliases", [])
        canonical = counts.get("normalized_canonical", [])
        verb = "would_normalize" if args.dry_run else "normalized"
        print(f"{verb}_aliases={len(aliases)}, {verb}_canonical_clubs={len(canonical)}")
        if aliases:
            print(f"{verb}_club_mappings=")
            for alias in aliases:
                print(f"  - {alias} -> {DEFAULT_REGISTRY.normalize_team_name(alias)}")

        if not args.dry_run:
            # Keep the UI game switcher consistent with any rewritten team labels.
            build_manifest(data_dir, args.seasoncode)
            print("manifest_rebuilt=1")
            if not args.skip_elo_refresh:
                compute_elo_for_season(output_dir=data_dir, seasoncode=args.seasoncode)
                recomputed, _payload, reason = recompute_multiseason_elo_if_needed(
                    output_dir=data_dir,
                    force=True,
                    output_name="elo_multiseason.json",
                )
                print("elo_season_rebuilt=1")
                print(f"elo_multiseason_rebuilt={'1' if recomputed else '0'} reason={reason}")

        unknown = find_unknown_club_names(data_dir=data_dir, seasoncodes=[args.seasoncode])
        if unknown:
            print("WARNING: unknown club names detected (not present in runtime registry):")
            for name in unknown:
                print(f"  - {name}")
            print("ACTION REQUIRED: update src/basket/clubs.yaml (name or registered_names_historically).")
        else:
            print("registry_check=ok (no unknown club names found)")
        return 0

    if command == "normalize_all_seasons":
        parser = argparse.ArgumentParser(description="Normalize/canonicalize all stored seasons in-place.")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing season JSON files (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=max(1, min(16, os.cpu_count() or 1)),
            help="Thread workers for concurrent file I/O (default: min(16, CPU count))",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
        parser.add_argument(
            "--skip-elo-refresh",
            action="store_true",
            help="Skip recomputing ELO payloads after normalization",
        )
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        seasoncodes: set[str] = set()
        for path in data_dir.glob("multi_drilldown_real_data_*_*.json"):
            m = re.match(r"multi_drilldown_real_data_(E\d{4})_\d+\.json$", path.name)
            if m:
                seasoncodes.add(m.group(1))

        if not seasoncodes:
            print(f"=== normalize_all_seasons {'DRY-RUN' if args.dry_run else 'LIVE'} in {data_dir} ===")
            print("No season files found.")
            return 0

        mode = "DRY-RUN" if args.dry_run else "LIVE"
        print(f"=== normalize_all_seasons ({mode}) in {data_dir} ===")
        all_aliases: set[str] = set()
        all_canonical: set[str] = set()
        for seasoncode in sorted(seasoncodes):
            counts = normalize_season_data_files(
                seasoncode=seasoncode,
                data_dir=data_dir,
                dry_run=args.dry_run,
                workers=args.workers,
            )
            print(
                f"{seasoncode}: files_total={counts['files_total']}, files_changed={counts['files_changed']}"
            )
            season_aliases = counts.get("normalized_aliases", [])
            season_canonical = counts.get("normalized_canonical", [])
            all_aliases.update(season_aliases)
            all_canonical.update(season_canonical)
            if season_aliases:
                verb = "would_normalize" if args.dry_run else "normalized"
                print(
                    f"{seasoncode}: {verb}_aliases={len(season_aliases)}, {verb}_canonical_clubs={len(season_canonical)}"
                )
            if not args.dry_run:
                build_manifest(data_dir, seasoncode)
                print(f"{seasoncode}: manifest_rebuilt=1")
                if not args.skip_elo_refresh:
                    compute_elo_for_season(output_dir=data_dir, seasoncode=seasoncode)
                    print(f"{seasoncode}: elo_rebuilt=1")

        verb = "would_normalize" if args.dry_run else "normalized"
        print(f"{verb}_aliases_total={len(all_aliases)}, {verb}_canonical_clubs_total={len(all_canonical)}")
        if all_aliases:
            print(f"{verb}_club_mappings=")
            for alias in sorted(all_aliases):
                print(f"  - {alias} -> {DEFAULT_REGISTRY.normalize_team_name(alias)}")

        if not args.dry_run and (not args.skip_elo_refresh):
            recomputed, _payload, reason = recompute_multiseason_elo_if_needed(
                output_dir=data_dir,
                force=True,
                output_name="elo_multiseason.json",
            )
            print(f"elo_multiseason_rebuilt={'1' if recomputed else '0'} reason={reason}")

        unknown = find_unknown_club_names(data_dir=data_dir, seasoncodes=sorted(seasoncodes))
        if unknown:
            print("WARNING: unknown club names detected (not present in runtime registry):")
            for name in unknown:
                print(f"  - {name}")
            print("ACTION REQUIRED: update src/basket/clubs.yaml (name or registered_names_historically).")
        else:
            print("registry_check=ok (no unknown club names found)")
        return 0

    if command == "backfill_gamedates":
        parser = argparse.ArgumentParser(description="Backfill meta.gamedate in stored season JSON files from raw Points payloads.")
        parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2025")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing processed season JSON files",
        )
        parser.add_argument(
            "--raw-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets"),
            help="Directory containing raw_pts_<season>_<game>.json files",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        raw_dir = Path(args.raw_dir).resolve()
        counts = backfill_season_gamedates(
            seasoncode=args.seasoncode,
            data_dir=data_dir,
            raw_dir=raw_dir,
            dry_run=args.dry_run,
        )
        mode = "DRY-RUN" if args.dry_run else "LIVE"
        print(f"=== backfill_gamedates ({mode}) {args.seasoncode} in {data_dir} using {raw_dir} ===")
        print(f"files_total={counts['files_total']}, files_changed={counts['files_changed']}, missing_raw={counts['missing_raw']}, missing_date={counts['missing_date']}")
        if not args.dry_run:
            build_manifest(data_dir, args.seasoncode)
            print("manifest_rebuilt=1")
        return 0

    if command == "check_dates":
        parser = argparse.ArgumentParser(description="Check how many stored game bundles have meta.gamedate populated.")
        parser.add_argument(
            "--data-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing processed game JSON files",
        )
        parser.add_argument("--seasoncode", default=None, help="Limit to a single season, e.g. E2025")
        args = parser.parse_args(rest)

        data_dir = Path(args.data_dir).resolve()
        pattern = f"multi_drilldown_real_data_{args.seasoncode or 'E*'}_*.json"
        files = sorted(data_dir.glob(pattern))

        total = 0
        with_date = 0
        missing: list[str] = []
        by_season: dict[str, tuple[int, int]] = {}

        for f in files:
            total += 1
            parts = f.stem.split("_")  # multi_drilldown_real_data_E2021_54
            season = parts[-2] if len(parts) >= 2 else "unknown"
            try:
                data = json.loads(f.read_text())
                gamedate = data.get("meta", {}).get("gamedate")
            except Exception:
                gamedate = None

            s_total, s_found = by_season.get(season, (0, 0))
            if gamedate:
                with_date += 1
                by_season[season] = (s_total + 1, s_found + 1)
            else:
                missing.append(f.name)
                by_season[season] = (s_total + 1, s_found)

        print(f"\n=== check_dates: {data_dir} ===")
        print(f"  games_total:   {total}")
        print(f"  dates_found:   {with_date}/{total}")
        print(f"  dates_missing: {total - with_date}")
        if by_season:
            print("  by_season:")
            for season in sorted(by_season):
                s_total, s_found = by_season[season]
                status = "ok" if s_found == s_total else f"MISSING {s_total - s_found}"
                print(f"    {season}: {s_found}/{s_total}  [{status}]")
        if missing:
            print(f"  missing_date_files ({len(missing)} total, first 20 shown):")
            for name in missing[:20]:
                print(f"    - {name}")
            if len(missing) > 20:
                print(f"    ... and {len(missing) - 20} more")
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
        print(f"earliest={report.earliest or 'n/a'}")
        print(f"latest={report.latest or 'n/a'}")
        print(f"distinct_teams={report.distinct_teams}")
        print("teams=")
        for t in report.teams:
            print(f"  - {t}")
        return 0

    if command == "report_inventory":
        parser = argparse.ArgumentParser(description="Report stored seasons inventory from JSON game files.")
        parser.add_argument(
            "--output-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory containing stored game JSON files (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        args = parser.parse_args(rest)
        print_stored_seasons_inventory(Path(args.output_dir).resolve(), print_if_empty=True)
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
        parser.add_argument("--seasoncode", default=None, help="Season code, e.g. E2021. Omit to index all seasons.")
        parser.add_argument("--all-seasons", action="store_true", help="Index all seasons found in output-dir (same as omitting --seasoncode).")
        parser.add_argument(
            "--output-dir",
            default=os.getenv("BASKET_APP_FILE_STORE_URI", "assets") + "/processed",
            help="Directory where JSON files live (default: BASKET_APP_FILE_STORE_URI/processed)",
        )
        args = parser.parse_args(rest)

        sc = None if (args.all_seasons or args.seasoncode is None) else args.seasoncode
        out_dir = Path(args.output_dir).resolve()
        label = sc if sc else "ALL seasons"
        print(f"=== Rebuilding manifest for {label} in {out_dir} ===")
        build_manifest(out_dir, sc)
        return 0

    if command == "build_score_timeline":
        from build_score_timeline import main as build_score_timeline_main

        return build_score_timeline_main(rest)

    if command == "style_insights":
        return style_insights_main(rest)

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
