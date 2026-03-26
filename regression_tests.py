from __future__ import annotations

"""Very small regression harness for the Euroleague Sankey spike.

This is intentionally lightweight and focuses on the specific bug we hit:
- Made 2 / Made 3 events were not showing up in the top view, because
  PlayType codes (2FGM/3FGM) were not mapped.

Running:
    python regression_tests.py

Exit code 0 => all checks passed.
Exit code 1 => at least one check failed.
"""

import json
from pathlib import Path
from typing import List, Tuple

from build_from_euroleague_api import run_game


Sample = Tuple[str, int]


def run_sample(seasoncode: str, gamecode: int) -> dict:
    """Run the pipeline for a given game without touching disk permanently."""
    tmp_name = f"_tmp_regression_{seasoncode}_{gamecode}.json"
    payload = run_game(seasoncode, gamecode, tmp_name)
    try:
        data = json.loads(Path(tmp_name).read_text(encoding="utf-8"))
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            # Python <3.8 compatibility if ever needed.
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
    return data


def assert_made_shots_present(payload: dict) -> None:
    views = payload.get("views", {})
    top = views.get("top", {})
    links = top.get("links", [])
    if not isinstance(links, list) or not links:
        raise AssertionError("top.links missing or empty")

    has_made2 = False
    has_made3 = False
    for link in links:
        if not isinstance(link, dict):
            continue
        target = str(link.get("target", ""))
        value = link.get("value", 0)
        try:
            value_num = int(value)
        except Exception:  # noqa: BLE001
            value_num = 0
        if value_num <= 0:
            continue
        if target.endswith("_2"):
            has_made2 = True
        if target.endswith("_3"):
            has_made3 = True

    if not (has_made2 or has_made3):
        raise AssertionError("Expected at least some Made 2 or Made 3 flows in top view")


def main() -> None:
    samples: List[Sample] = [
        ("E2021", 54),
        ("E2021", 55),
    ]

    failures: List[str] = []

    for seasoncode, gamecode in samples:
        label = f"{seasoncode} / {gamecode}"
        print(f"[RUN] {label}")
        try:
            payload = run_sample(seasoncode, gamecode)
            assert_made_shots_present(payload)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {exc}")
            print(f"  [FAIL] {exc}")
        else:
            print("  [OK] Made 2/3 flows present in top view")

    if failures:
        print("\nRegression failures:")
        for msg in failures:
            print(" -", msg)
        raise SystemExit(1)

    print("\nAll regression checks passed.")


if __name__ == "__main__":
    main()
