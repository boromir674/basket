#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
from typing import List


def find_files(directory: Path, pattern: str) -> List[Path]:
    if not directory.exists():
        return []
    out: List[Path] = []
    for root, _, files in os.walk(directory):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                out.append(Path(root) / name)
    return sorted(out)


def validate(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as f:
            json.load(f)
        return True
    except Exception as exc:
        print(f"  [INVALID] {path}: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate processed JSON files under /app/assets/processed.")
    parser.add_argument("pattern", nargs="?", default="*.json", help="Filename glob pattern to validate (default: '*.json')")
    args = parser.parse_args()

    directory = Path("/app/assets/processed")
    print(f"Looking inside directory: {directory} for pattern: {args.pattern}\n")

    files = find_files(directory, args.pattern)
    if not files:
        print("No files found matching pattern.")
        return

    total = len(files)
    valid = 0
    invalid_files: List[Path] = []

    for p in files:
        print(f"Checking {p}")
        ok = validate(p)
        if ok:
            valid += 1
        else:
            invalid_files.append(p)

    print("\nSummary:")
    print(f"  files checked: {total}")
    print(f"  valid:         {valid}")
    print(f"  invalid:       {len(invalid_files)}")

    if invalid_files:
        print("\nInvalid files:")
        for p in invalid_files:
            print(f" - {p}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
