from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from build_from_euroleague_api import run_game
from build_score_timeline import build_timeline_payload
from basket.logging_utils import configure_logging
from validate_output import validate_file


TAIL_MISS_THRESHOLD = 5


def _collect_stored_seasons_inventory(output_dir: Path) -> list[dict[str, Any]]:
    """Aggregate stored game files by season with counts and date range."""
    by_season: dict[str, dict[str, Any]] = {}
    for path in sorted(output_dir.glob("multi_drilldown_real_data_*_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            continue

        seasoncode = meta.get("seasoncode")
        gamedate = meta.get("gamedate")
        if not isinstance(seasoncode, str) or not seasoncode:
            continue
        if not isinstance(gamedate, str) or not gamedate:
            gamedate = None

        row = by_season.setdefault(
            seasoncode,
            {
                "seasoncode": seasoncode,
                "games": 0,
                "earliest": None,
                "latest": None,
            },
        )
        row["games"] += 1
        if gamedate is None:
            continue
        if row["earliest"] is None or gamedate < row["earliest"]:
            row["earliest"] = gamedate
        if row["latest"] is None or gamedate > row["latest"]:
            row["latest"] = gamedate

    return [by_season[k] for k in sorted(by_season.keys())]


def print_stored_seasons_inventory(output_dir: Path, *, print_if_empty: bool = False) -> int:
    """Print season inventory summary and return number of seasons reported."""
    rows = _collect_stored_seasons_inventory(output_dir)
    if not rows and not print_if_empty:
        return 0

    print("\n[INFO] Stored seasons inventory:")
    if not rows:
        print("  (no season game files found)")
        return 0

    for row in rows:
        earliest = row["earliest"] if row["earliest"] is not None else "n/a"
        latest = row["latest"] if row["latest"] is not None else "n/a"
        print(f"  {row['seasoncode']}: games={row['games']} earliest={earliest} latest={latest}")

    return len(rows)


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
    if isinstance(exc, ValueError) and "game not available" in str(exc):
        return "permanent", "game not available (no data from API)"
    return "transient", f"{type(exc).__name__}: {exc}"


def _build_one_game(
    *,
    seasoncode: str,
    gamecode: int,
    out_path: Path,
    raw_dir: Optional[Path] = None,
    score_timeline_dir: Optional[Path] = None,
) -> tuple[bool, Optional[dict[str, Any]], str, str]:
    """Build+validate a single game. Returns (ok, meta, err_kind, err_msg).

    Also writes score_timeline_{seasoncode}_{gamecode}.json if raw_dir and
    score_timeline_dir are provided (raw_pts file must exist after run_game).
    """
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

        # Build score_timeline artifact from the raw_pts file written by run_game.
        if raw_dir is not None and score_timeline_dir is not None:
            raw_pts = raw_dir / f"raw_pts_{seasoncode}_{gamecode}.json"
            if raw_pts.exists():
                try:
                    payload = build_timeline_payload(raw_pts)
                    tl_path = score_timeline_dir / f"score_timeline_{seasoncode}_{gamecode}.json"
                    tl_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as tl_exc:  # noqa: BLE001
                    logging.getLogger("season_sync").warning(
                        "score_timeline build failed for %s/%s: %s", seasoncode, gamecode, tl_exc
                    )

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


def build_manifest(output_dir: Path, seasoncode: str | None = None) -> None:
    """Scan JSON files and write a simple manifest for the UI.

    If seasoncode is None, all seasons found in output_dir are indexed.
    Backwards compatible: passing a single seasoncode still works as before.

    Manifest shape (unchanged, multi-season just means more entries):
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

    # Determine which seasons to index
    if seasoncode is not None:
        seasoncodes = [seasoncode]
    else:
        # Auto-detect all seasons present in the directory
        import re as _re
        detected = set()
        for p in output_dir.glob("multi_drilldown_real_data_E*.json"):
            m = _re.match(r"multi_drilldown_real_data_(E\d+)_", p.name)
            if m:
                detected.add(m.group(1))
        seasoncodes = sorted(detected)

    for sc in seasoncodes:
        elo_ratings = _load_elo_ratings(output_dir, sc)
        pattern = f"multi_drilldown_real_data_{sc}_*.json"
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
                    "seasoncode": sc,
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
    parser = argparse.ArgumentParser(
        description="Sync all games for a season by scanning gamecodes from 1 until tail miss threshold is reached."
    )
    parser.add_argument("--seasoncode", required=True, help="Season code, e.g. E2024")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where JSON files will be written (default: current directory)",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=25,
        help="Stop early after this many non-permanent failures (network/rate-limit)",
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
        help="Print a progress update every N scanned gamecodes (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_env_int("BASKET_SYSTEM_SYNC_CONCURRENCY", 1),
        help="Deprecated for season_sync scan mode (sequential only).",
    )
    parser.add_argument(
        "--pressure",
        type=float,
        default=_env_float("BASKET_SYSTEM_API_PRESSURE", 1.0),
        help="Deprecated for season_sync scan mode (sequential only).",
    )
    parser.add_argument(
        "--pressure-decay",
        type=float,
        default=0.7,
        help="Deprecated for season_sync scan mode (sequential only).",
    )
    parser.add_argument(
        "--pressure-inc",
        type=float,
        default=0.05,
        help="Deprecated for season_sync scan mode (sequential only).",
    )
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=1.0,
        help="Base backoff seconds on 429 during retry pass (default: 1.0)",
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
        help="After initial scan, retry failed gamecodes sequentially",
    )
    parser.add_argument(
        "--write-failures",
        action="store_true",
        help="Write a failures JSON file to output-dir",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No-op summary for scan mode (open-ended scan cannot be dry-run enumerated)",
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
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # raw_dir: where build_from_euroleague_api.py writes raw_pts/raw_pbp/raw_box files.
    raw_dir = Path(os.getenv("BASKET_APP_FILE_STORE_URI", "assets")).resolve()
    # score_timeline files live alongside the processed game JSONs.
    score_timeline_dir = output_dir

    # Logging: console INFO by default, file DEBUG by default.
    if str(args.log_file).strip():
        log_path = Path(str(args.log_file)).expanduser()
    else:
        log_path = output_dir / "logs" / f"season_sync_{seasoncode}_{int(time.time())}.log"
    configured = configure_logging(console_level=args.log_level, log_file=log_path, file_level="DEBUG")
    logger = logging.getLogger("season_sync")
    if configured is not None:
        logger.info("File logging enabled -> %s", configured)

    if args.concurrency and args.concurrency > 1:
        logger.info("Ignoring --concurrency=%s; scan mode is sequential by design.", args.concurrency)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    logger.info(
        "=== Season sync for %s: scan from gamecode=1 until %s consecutive permanent misses (mode=%s) ===",
        seasoncode,
        TAIL_MISS_THRESHOLD,
        mode,
    )

    if args.dry_run:
        print("\n[INFO] Dry-run not executed: season sync now scans until tail stop condition and has no fixed range.")
        print(f"  seasoncode: {seasoncode}")
        print(f"  stop_condition: {TAIL_MISS_THRESHOLD} consecutive permanent missing gamecodes")
        return 0

    failures = 0
    blocking_failures = 0
    processed = 0
    skipped_existing = 0
    scanned_total = 0
    first_game_meta = None
    prompted_after_first = False
    found_gamecodes: set[int] = set()

    print("\n[INFO] Starting season ingestion:")
    print(f"  seasoncode: {seasoncode}")
    print("  scan_mode: sequential from gamecode=1")
    print(f"  stop_condition: {TAIL_MISS_THRESHOLD} consecutive permanent missing gamecodes (tail)")

    failed: list[dict[str, Any]] = []

    def record_failure(gamecode: int, kind: str, msg: str) -> None:
        failed.append({"seasoncode": seasoncode, "gamecode": gamecode, "kind": kind, "message": msg})

    def maybe_write_failures() -> None:
        if not args.write_failures:
            return
        p = output_dir / f"season_sync_failures_{seasoncode}.json"
        p.write_text(json.dumps(failed, indent=2), encoding="utf-8")
        print(f"Wrote failures ({len(failed)}) -> {p}")

    def _split_tail_vs_holes(entries: list[dict[str, Any]], successes: set[int]):
        permanent = sorted(
            [e for e in entries if e.get("kind") == "permanent"],
            key=lambda e: e.get("gamecode", 0),
        )
        other = [e for e in entries if e.get("kind") != "permanent"]

        if not permanent:
            return [], [], other

        tail_set = set()
        prev = int(permanent[-1].get("gamecode", 0))
        tail_set.add(prev)
        for entry in reversed(permanent[:-1]):
            gc = int(entry.get("gamecode", 0))
            if prev - gc == 1:
                tail_set.add(gc)
                prev = gc
            else:
                break

        tail = [e for e in permanent if int(e.get("gamecode", 0)) in tail_set]
        holes_raw = [e for e in permanent if int(e.get("gamecode", 0)) not in tail_set]
        if not successes:
            return tail, [], other

        min_found = min(successes)
        max_found = max(successes)
        holes = [
            e for e in holes_raw
            if min_found < int(e.get("gamecode", 0)) < max_found
        ]
        return tail, holes, other

    def print_failure_diagnostics(*, stopped_early: bool) -> None:
        if not failed:
            return

        by_kind = Counter(entry.get("kind", "unknown") for entry in failed)

        def classify_exception_name(msg: str) -> str:
            m = str(msg or "")
            if "RequestException:" in m:
                return m.split("RequestException:", 1)[1].strip() or "RequestException"
            if m.startswith("HTTP "):
                return m.split()[1] if len(m.split()) > 1 else "HTTP"
            if ":" in m:
                return m.split(":", 1)[0].strip() or "Unknown"
            return m or "Unknown"

        tail, holes, other_failures = _split_tail_vs_holes(failed, found_gamecodes)

        print("\n[INFO] Failure diagnostics:")
        print(f"  failures_total: {len(failed)}")
        print(f"  stopped_early: {'yes' if stopped_early else 'no'}")

        if tail:
            tail_gcs = sorted(int(e.get("gamecode", 0)) for e in tail)
            print(f"  end_of_season_tail: {len(tail)} gamecodes ({tail_gcs[0]}–{tail_gcs[-1]}) — no data on API, expected")

        if holes:
            hole_gcs = sorted(int(e.get("gamecode", 0)) for e in holes)
            print(f"  mid_season_holes: {len(holes)} gamecodes")
            print(f"    gamecodes: {hole_gcs}")
            print("    NOTE: hole(s) do not stop ingestion; they are reported only.")

        if other_failures:
            print("  retriable_failures:")
            by_other = Counter(e.get("kind", "unknown") for e in other_failures)
            by_exc = Counter(classify_exception_name(str(e.get("message", ""))) for e in other_failures)
            for kind, cnt in by_other.most_common():
                print(f"    - {kind}: {cnt}")
            for exc, cnt in by_exc.most_common(5):
                print(f"    - exception: {exc}: {cnt}")

        joined = " | ".join(str(entry.get("message", "")) for entry in failed)
        hints = []
        if by_kind.get("rate_limited", 0) > 0 or "HTTP 429" in joined:
            hints.append("API rate limiting detected: lower load and keep --retry-pass enabled.")
        if "ReadTimeout" in joined or "ConnectTimeout" in joined or "ConnectionError" in joined:
            hints.append("Network instability detected: rerun; transient failures should recover.")
        if hints:
            print("  mitigation:")
            for h in hints:
                print(f"    - {h}")

    started_at = time.time()
    next_gamecode = 1
    tail_miss_streak = 0

    while True:
        if blocking_failures >= args.max_failures:
            logger.error("Too many non-permanent failures, stopping early.")
            break

        gamecode = next_gamecode
        next_gamecode += 1
        scanned_total += 1

        out_name = f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
        out_path = output_dir / out_name

        if out_path.exists() and not args.force:
            skipped_existing += 1
            found_gamecodes.add(gamecode)
            tail_miss_streak = 0
            if scanned_total % max(1, args.progress_interval) == 0:
                logger.info(
                    "[PROGRESS] scanned=%s, ok=%s, skipped=%s, failures=%s, tail_miss_streak=%s",
                    scanned_total,
                    processed,
                    skipped_existing,
                    failures,
                    tail_miss_streak,
                )
            continue

        logger.info("[RUN] %s/%s -> %s", seasoncode, gamecode, out_path)
        ok, meta, kind, msg = _build_one_game(
            seasoncode=seasoncode, gamecode=gamecode, out_path=out_path,
            raw_dir=raw_dir, score_timeline_dir=score_timeline_dir,
        )

        if not ok:
            logger.warning("[ERROR %s] %s/%s: %s", kind, seasoncode, gamecode, msg)
            failures += 1
            record_failure(gamecode, kind, msg)

            if kind == "permanent":
                tail_miss_streak += 1
            else:
                blocking_failures += 1
                tail_miss_streak = 0

            if tail_miss_streak >= TAIL_MISS_THRESHOLD:
                logger.info(
                    "Reached tail stop condition at gamecode=%s (%s consecutive permanent misses)",
                    gamecode,
                    tail_miss_streak,
                )
                break
            continue

        # Success path
        found_gamecodes.add(gamecode)
        tail_miss_streak = 0

        if processed == 0 and meta is not None:
            first_game_meta = meta
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
            "Downloaded OK: %s (scanned=%s, skipped=%s, failures=%s) | %.2f games/s | elapsed=%.1fs",
            processed,
            scanned_total,
            skipped_existing,
            failures,
            rate,
            elapsed,
        )
        if scanned_total % max(1, args.progress_interval) == 0:
            logger.info(
                "[PROGRESS] scanned=%s, ok=%s, skipped=%s, failures=%s, tail_miss_streak=%s",
                scanned_total,
                processed,
                skipped_existing,
                failures,
                tail_miss_streak,
            )

    # Retry pass for failed gamecodes (sequential)
    if args.retry_pass and failed and blocking_failures < args.max_failures:
        backoff_base = max(0.0, float(args.backoff_seconds))
        backoff_cap = max(0.0, float(args.max_backoff_seconds))
        logger.info("=== Retry pass (sequential) for %s failed games ===", len(failed))
        retry_failed = list(failed)
        failed.clear()
        for entry in retry_failed:
            gamecode = int(entry["gamecode"])
            out_path = output_dir / f"multi_drilldown_real_data_{seasoncode}_{gamecode}.json"
            logger.info("[RETRY] %s/%s", seasoncode, gamecode)
            ok, _meta, kind, msg = _build_one_game(
                seasoncode=seasoncode, gamecode=gamecode, out_path=out_path,
                raw_dir=raw_dir, score_timeline_dir=score_timeline_dir,
            )
            if ok:
                processed += 1
                found_gamecodes.add(gamecode)
            else:
                failures += 1
                record_failure(gamecode, kind, msg)
                if kind != "permanent":
                    blocking_failures += 1
                    if blocking_failures >= args.max_failures:
                        logger.error("Too many non-permanent failures, stopping early.")
                        break
                if kind == "rate_limited" and backoff_base > 0:
                    sleep_s = min(backoff_cap, backoff_base)
                    if sleep_s > 0:
                        time.sleep(sleep_s)

    logger.info("=== Done. processed=%s, failures=%s (mode=%s) ===", processed, failures, mode)
    maybe_write_failures()
    print_failure_diagnostics(stopped_early=blocking_failures >= args.max_failures)
    print("\n[INFO] Season ingestion summary:")
    print(f"  seasoncode: {seasoncode}")
    print(f"  scanned_gamecodes: {scanned_total}")
    print(f"  downloaded_ok: {processed}")
    print(f"  skipped_existing: {skipped_existing}")
    print(f"  failures: {failures}")
    print_stored_seasons_inventory(output_dir)

    if processed > 0:
        build_manifest(output_dir, seasoncode)
    else:
        logger.warning("No successful games; manifest not updated")

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
