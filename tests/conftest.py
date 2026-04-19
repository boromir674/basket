from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """Ensure `src/` is importable in local runs.

    Docker sets PYTHONPATH=/app/src, but local `pytest` typically doesn't.
    """

    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"

    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
