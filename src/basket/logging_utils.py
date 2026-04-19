from __future__ import annotations

import logging
from pathlib import Path


def _coerce_level(level: str | int | None, *, default: int) -> int:
    if level is None:
        return default
    if isinstance(level, int):
        return level
    s = str(level).strip().upper()
    if not s:
        return default
    return int(getattr(logging, s, default))


def configure_logging(
    *,
    console_level: str | int | None = "INFO",
    log_file: str | Path | None,
    file_level: str | int | None = "DEBUG",
) -> Path | None:
    """Configure root logging.

    - Console defaults to INFO.
    - File defaults to DEBUG (all logs).
    """

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(_coerce_level(console_level, default=logging.INFO))
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(_coerce_level(file_level, default=logging.DEBUG))
        fh.setFormatter(fmt)
        root.addHandler(fh)
        return path

    return None
