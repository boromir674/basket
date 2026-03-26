from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple


def validate_file(path: Path) -> Tuple[bool, str]:
    """Validate a single Sankey JSON file according to lightweight rules.

    Returns (is_valid, message).
    """
    if not path.is_file():
        return False, "file does not exist"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid JSON: {exc}"

    if not isinstance(data, dict):
        return False, "root is not an object"

    meta = data.get("meta")
    views = data.get("views")
    if not isinstance(meta, dict):
        return False, "missing or invalid 'meta' section"
    if not isinstance(views, dict):
        return False, "missing or invalid 'views' section"

    top = views.get("top")
    if not isinstance(top, dict):
        return False, "missing 'top' view"

    nodes = top.get("nodes")
    links = top.get("links")
    if not isinstance(nodes, list) or not nodes:
        return False, "'top.nodes' is missing or empty"
    if not isinstance(links, list) or not links:
        return False, "'top.links' is missing or empty"

    # Heuristic: ensure there is at least some non-zero Made 2 or Made 3
    # scoring represented in the top view. This is intentionally light-
    # touch and just guards against obviously empty scoring data.
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
        return False, "no non-zero Made 2 or Made 3 flows detected in top view"

    return True, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one or more Euroleague Sankey JSON files.")
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON file(s) to validate",
    )
    args = parser.parse_args()

    paths: List[Path] = [Path(p).resolve() for p in args.files]

    any_failed = False
    for path in paths:
        is_valid, message = validate_file(path)
        status = "OK" if is_valid else "FAIL"
        print(f"[{status}] {path}: {message}")
        if not is_valid:
            any_failed = True

    if any_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
