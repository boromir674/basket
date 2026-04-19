from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from build_from_euroleague_api import run_game
from basket.logging_utils import configure_logging
from validate_output import validate_file


def _env_int(name: str, default: int) -> int:
    try:
        v = str(os.getenv(name, "")).strip()
    except Exception:
        v = ""
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = str(os.getenv(name, "")).strip()
    except Exception:
        v = ""
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _classify_error(exc: BaseException) -> tuple[str, str]:
    """Return (kind, message) where kind is one of: rate_limited, transient, permanent."""
    # 429 / Too Many Requests
    try:
        import requests

        if isinstance(exc, requests.exceptions.HTTPError):
            resp = getattr(exc, "response", None)
            code = getattr(resp, "status_code", None)
            if code == 429:
                return "rate_limited", "HTTP 429 Too Many Requests"
            if code is not None:
                return "transient", f"HTTP {code}"
            return "transient", "HTTP error"
        if isinstance(exc, requests.exceptions.RequestException):
            return "transient", f"RequestException: {type(exc).__name__}"
    except Exception:
        pass

    if isinstance(exc, SystemExit):
        return "permanent", f"SystemExit: {exc}"
    return "transient", f"{type(exc).__name__}: {exc}"


def _build_one_game(
    *,
    seasoncode: str,
    gamecode: int,
    out_path: Path,
) -> tuple[bool, Optional[dict[str, Any]], str, str]:
    """Build+validate a single game. Returns (ok, meta, err_kind, err_msg)."""
    try:
        run_game(seasoncode, gamecode, str(out_path))
        is_valid, message = validate_file(out_path)
        if not is_valid:
            return False, None, "permanent", f"validation failed: {message}"

        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
        except Exception:
            meta = None

        return True, meta, "", ""
    except BaseException as exc:  # noqa: BLE001
        kind, msg = _classify_error(exc)
        return False, None, kind, msg


def _load_elo_ratings(output_dir: Path, seasoncode: str) -> Dict[str, float]:
    """Load team ELO ratings from elo_{seasoncode}.json if it exists."""
    elo_path = output_dir / f"elo_{seasoncode}.json"
    if not elo_path.exists():
        return {}
    try:
        data = json.loads(elo_path.read_text(encoding="utf-8"))
        ratings = data.get("ratings", {})
        if isinstance(ratings, dict):
            return {str(k): float(v) for k, v in ratings.items()}
    except Exception:  # noqa: BLE001
        pass
    return {}


def build_manifest(output_dir: Path, seasoncode: str) -> None:
    """Scan JSON files and write a simple manifest for the UI.

    Manifest shape:
    [{"file": "multi_drilldown_real_data_E2021_54.json",
      "seasoncode": "E2021",
      "gamecode": 54,
      "team_a": "...",
      "team_b": "...",
      "score_a": 85,
      "score_b": 78,
      "winner": "...",
      "elo_a": 1563.0,
      "elo_b": 1488.0}, ...]
    """
    entries: List[Dict[str, Any]] = []
    elo_ratings = _load_elo_ratings(output_dir, seasoncode)

    pattern = f"multi_drilldown_real_data_{seasoncode}_*.json"
    for path in sorted(output_dir.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {})
        try:
            gamecode = int(meta.get("gamecode"))
        except Exception:  # noqa: BLE001
            continue
        team_a = meta.get("team_a")
        team_b = meta.get("team_b")
        entries.append(
            {
                "file": path.name,
                "seasoncode": seasoncode,
                "gamecode": gamecode,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": meta.get("score_a"),
                "score_b": meta.get("score_b"),
                "winner": meta.get("winner"),
                "elo_a": elo_ratings.get(team_a),
                "elo_b": elo_ratings.get(team_b),
                "gamedate": meta.get("gamedate"),
                "synced_at": meta.get("synced_at"),
            }
        )

    manifest_path = output_dir / "games_manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("Wrote manifest with %s entries -> %s", len(entries), manifest_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync a block of games for a season.")
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2024")
    parser.add_argument("--start-gamecode", type=int, default=1, help="First gamecode to try (inclusive)")
    parser.add_argument("--end-gamecode", type=int, default=200, help="Last gamecode to try (inclusive)")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where JSON files will be written (default: current directory)",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=25,
        help="Stop early after this many failures (e.g. missing games)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild games even if output JSON already exists",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="After the first successful game build, prompt user to confirm continuing",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive accept prompts (implies --interactive)",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="Print a progress update every N processed games (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_env_int("BASKET_SYSTEM_SYNC_CONCURRENCY", 1),
        help="Max concurrent game builds (default: env BASKET_SYSTEM_SYNC_CONCURRENCY or 1)",
    )
    parser.add_argument(
        "--pressure",
        type=float,
        default=_env_float("BASKET_SYSTEM_API_PRESSURE", 1.0),
        help="Initial API pressure in [0,1] (scales concurrency). Default: env BASKET_SYSTEM_API_PRESSURE or 1.0",
    )
    parser.add_argument(
        "--pressure-decay",
        type=float,
        default=0.7,
        help="On HTTP 429, multiply pressure by this factor (default: 0.7)",
    )
    parser.add_argument(
        "--pressure-inc",
        type=float,
        default=0.05,
        help="When stable (no 429s), add this to pressure periodically (default: 0.05)",
    )
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=1.0,
        help="Base backoff seconds on 429 (default: 1.0)",
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=float,
        default=20.0,
        help="Maximum backoff sleep seconds on repeated 429s (default: 20.0)",
    )
    parser.add_argument(
        "--retry-pass",
        action="store_true",
        help="After concurrent pass, retry failed games sequentially",
    )
    parser.add_argument(
        "--write-failures",
        action="store_true",
        help="Write a failures JSON file to output-dir",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write or validate JSON, just log what would be done",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Console log level (default: INFO). Use DEBUG for verbose output.",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Log file path. Default: <output-dir>/logs/season_sync_<seasoncode>_<ts>.log",
    )

    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)

    seasoncode: str = args.seasoncode
    start_gc: int = args.start_gamecode
    end_gc: int = args.end_gamecode
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Logging: console INFO by default, file DEBUG by default.
    if str(args.log_file).strip():
        log_path = Path(str(args.log_file)).expanduser()
    else:
        log_path = output_dir / "logs" / f"season_sync_{seasoncode}_{int(time.time())}.log"
    configured = configure_logging(console_level=args.log_level, log_file=log_path, file_level="DEBUG")
    logger = logging.getLogger("season_sync")
    if configured is not None:
        logger.info("File logging enabled -> %s", configured)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    logger.info("=== Season sync for %s: %s..%s (mode=%s) ===", seasoncode, start_gc, end_gc, mode)

    failures = 0
    processed = 0
    first_game_meta = None
    first_game_year = None
    prompted_after_first = False

    # If interactive prompting is requested, force sequential mode so we don't
    # schedule work ahead of user confirmation.
    if args.interactive and args.concurrency and args.concurrency > 1:
        print("[NOTICE] --interactive requested; forcing --concurrency=1")
        args.concurrency = 1

    # Build target list (respects --force and existing files).
    targets: list[int] = []
    for gamecode in range(start_gc, end_gc + 1):
        out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name
        if out_path.exists() and not args.force:
            continue
        targets.append(gamecode)

    started_at = time.time()
    total_to_build = len(targets)
    logger.info("Planned builds: %s games (skipping existing unless --force)", total_to_build)

    failed: list[dict[str, Any]] = []

    def record_failure(gamecode: int, kind: str, msg: str) -> None:
        failed.append({"seasoncode": seasoncode, "gamecode": gamecode, "kind": kind, "message": msg})

    def maybe_write_failures() -> None:
        if not args.write_failures:
            return
        p = output_dir / f"season_sync_failures_{seasoncode}.json"
        p.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        print(f"Wrote failures ({len(failed)}) -> {p}")

    if args.dry_run:
        for gamecode in targets:
            out_path = output_dir / f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            logger.info("[DRY-RUN] would build %s/%s -> %s", seasoncode, gamecode, out_path)
            processed += 1
        logger.info("=== Done. processed=%s, failures=%s (mode=%s) ===", processed, failures, mode)
        return 0

    # Sequential mode (preserves previous behavior).
    if not args.concurrency or args.concurrency <= 1:
        for gamecode in range(start_gc, end_gc + 1):
            out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            out_path = output_dir / out_name

            if out_path.exists() and not args.force:
                logger.debug("[SKIP existing] %s/%s -> %s", seasoncode, gamecode, out_path)
                continue

            logger.info("[RUN] %s/%s -> %s", seasoncode, gamecode, out_path)
            ok, meta, kind, msg = _build_one_game(seasoncode=seasoncode, gamecode=gamecode, out_path=out_path)
            if not ok:
                logger.warning("[ERROR %s] %s/%s: %s", kind, seasoncode, gamecode, msg)
                failures += 1
                record_failure(gamecode, kind, msg)
                if failures >= args.max_failures:
                    logger.error("Too many failures, stopping early.")
                    break
                continue

            logger.debug("[VALIDATION OK] %s/%s", seasoncode, gamecode)

            # on first successful processed game, record metadata and optionally prompt
            if processed == 0 and meta is not None:
                first_game_meta = meta
                gamedate = meta.get("gamedate") if isinstance(meta, dict) else None
                if gamedate and isinstance(gamedate, str) and len(gamedate) >= 4:
                    try:
                        first_game_year = int(gamedate[:4])
                    except Exception:
                        first_game_year = None
                print("\n[INFO] First successful game fetched:")
                print(f"  seasoncode: {meta.get('seasoncode')}")
                print(f"  gamecode:   {meta.get('gamecode')}")
                print(f"  gamedate:   {meta.get('gamedate')}")
                if args.interactive and not prompted_after_first:
                    if args.yes:
                        print("  [INTERACTIVE] --yes set, continuing without prompt")
                    else:
                        ans = input("Proceed with the rest of the season? [y/N]: ")
                        if ans.strip().lower() not in ("y", "yes"):
                            print("Aborting as requested by user.")
                            break
                    prompted_after_first = True

            processed += 1
            elapsed = max(0.001, time.time() - started_at)
            rate = processed / elapsed
            logger.info(
                "Downloaded OK: %s/%s (failures=%s) | %.2f games/s | elapsed=%.1fs",
                processed,
                total_to_build,
                failures,
                rate,
                elapsed,
            )
            if processed % args.progress_interval == 0:
                logger.info("[PROGRESS] ok=%s, failures=%s", processed, failures)

        logger.info("=== Done. processed=%s, failures=%s (mode=%s) ===", processed, failures, mode)
        maybe_write_failures()

        # Avoid clobbering an existing manifest with an empty one when a probe run
        # (or a bad seasoncode) yields zero successful games.
        if processed > 0 or total_to_build == 0:
            build_manifest(output_dir, seasoncode)
        else:
            logger.warning("No successful games; manifest not updated")
        return 0

    # Concurrent mode (game-level overlap).
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_conc = max(1, int(args.concurrency))
    pressure = _clamp(float(args.pressure), 0.05, 1.0)
    decay = _clamp(float(args.pressure_decay), 0.1, 1.0)
    inc = _clamp(float(args.pressure_inc), 0.0, 0.5)
    backoff_base = max(0.0, float(args.backoff_seconds))
    backoff_cap = max(0.0, float(args.max_backoff_seconds))

    consecutive_429 = 0
    stable_batches = 0

    logger.info(
        "[CONCURRENCY] enabled: max_concurrency=%s, initial_pressure=%.2f (effective=%s)",
        max_conc,
        pressure,
        max(1, round(max_conc * pressure)),
    )

    idx = 0
    with ThreadPoolExecutor(max_workers=max_conc) as ex:
        while idx < len(targets):
            if failures >= args.max_failures:
                logger.error("Too many failures, stopping early.")
                break

            eff = max(1, int(round(max_conc * pressure)))
            batch = targets[idx : idx + eff]
            idx += len(batch)

            futures = {}
            for gamecode in batch:
                out_path = output_dir / f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
                futures[ex.submit(_build_one_game, seasoncode=seasoncode, gamecode=gamecode, out_path=out_path)] = gamecode

            batch_429 = 0
            for fut in as_completed(list(futures.keys())):
                gamecode = futures[fut]
                ok, meta, kind, msg = fut.result()
                if ok:
                    processed += 1
                    if first_game_meta is None and meta is not None:
                        first_game_meta = meta
                    elapsed = max(0.001, time.time() - started_at)
                    rate = processed / elapsed
                    logger.info(
                        "[OK] %s/%s | Downloaded OK: %s/%s (failures=%s) | %.2f games/s | elapsed=%.1fs",
                        seasoncode,
                        gamecode,
                        processed,
                        total_to_build,
                        failures,
                        rate,
                        elapsed,
                    )
                else:
                    logger.warning("[FAIL %s] %s/%s: %s", kind, seasoncode, gamecode, msg)
                    failures += 1
                    record_failure(gamecode, kind, msg)
                    if kind == "rate_limited":
                        batch_429 += 1

            # Pressure update
            if batch_429 > 0:
                consecutive_429 += 1
                stable_batches = 0
                pressure = _clamp(pressure * decay, 0.05, 1.0)
                if backoff_base > 0:
                    sleep_s = min(backoff_cap, backoff_base * (2 ** (consecutive_429 - 1)))
                    if sleep_s > 0:
                        logger.info(
                            "[BACKOFF] 429s=%s consecutive=%s pressure=%.2f sleep=%.1fs",
                            batch_429,
                            consecutive_429,
                            pressure,
                            sleep_s,
                        )
                        time.sleep(sleep_s)
            else:
                consecutive_429 = 0
                stable_batches += 1
                if stable_batches >= 3 and inc > 0:
                    pressure = _clamp(pressure + inc, 0.05, 1.0)
                    stable_batches = 0
                    logger.info(
                        "[RAMP] pressure increased to %.2f (effective=%s)",
                        pressure,
                        max(1, round(max_conc * pressure)),
                    )

            if (processed + failures) % max(1, args.progress_interval) == 0:
                logger.info("[PROGRESS] ok=%s, failures=%s, pressure=%.2f", processed, failures, pressure)

    # Pass 2: retry failures sequentially (fallback).
    if args.retry_pass and failed and failures < args.max_failures:
        logger.info("=== Retry pass (sequential) for %s failed games ===", len(failed))
        retry_failed = list(failed)
        failed.clear()
        for entry in retry_failed:
            gamecode = int(entry["gamecode"])
            out_path = output_dir / f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            logger.info("[RETRY] %s/%s", seasoncode, gamecode)
            ok, _meta, kind, msg = _build_one_game(seasoncode=seasoncode, gamecode=gamecode, out_path=out_path)
            if ok:
                processed += 1
                elapsed = max(0.001, time.time() - started_at)
                rate = processed / elapsed
                logger.info(
                    "[OK] %s/%s | Downloaded OK: %s/%s (failures=%s) | %.2f games/s | elapsed=%.1fs",
                    seasoncode,
                    gamecode,
                    processed,
                    total_to_build,
                    failures,
                    rate,
                    elapsed,
                )
            else:
                logger.warning("[FAIL %s] %s/%s: %s", kind, seasoncode, gamecode, msg)
                failures += 1
                record_failure(gamecode, kind, msg)
                if failures >= args.max_failures:
                    logger.error("Too many failures, stopping early.")
                    break
                if kind == "rate_limited" and backoff_base > 0:
                    sleep_s = min(backoff_cap, backoff_base)
                    if sleep_s > 0:
                        time.sleep(sleep_s)

    logger.info("=== Done. processed=%s, failures=%s (mode=%s) ===", processed, failures, mode)
    maybe_write_failures()

    # Refresh manifest for this season so the UI can list all games.
    # If we had zero successes (e.g. probing a non-existent seasoncode), do not
    # clobber an existing manifest with an empty file.
    if processed > 0 or total_to_build == 0:
        build_manifest(output_dir, seasoncode)
    else:
        logger.warning("No successful games; manifest not updated")

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
