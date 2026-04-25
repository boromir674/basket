from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml
from attrs import define, field

# YAML source of truth lives next to this module.
_CLUBS_YAML = Path(__file__).parent / "clubs.yaml"


def _slug(name: str) -> str:
    """Derive a stable ID from a canonical name: lowercase, spaces → dashes."""
    return re.sub(r"\s+", "-", name.strip().lower())


@define(frozen=True, slots=True)
class BasketballClub:
    """Declarative club entity.

    `canonical_name` is the internal stable identifier we want everywhere.
    `id` is a URL/DB-safe slug derived from canonical_name.
    `aliases` lists known upstream variants (sponsor drift, spelling, legacy).
    """

    canonical_name: str
    aliases: tuple[str, ...] = field(factory=tuple, converter=tuple)

    @property
    def id(self) -> str:
        return _slug(self.canonical_name)

    def all_names(self) -> tuple[str, ...]:
        return (self.canonical_name, *self.aliases)


@define(frozen=True, slots=True)
class ClubRegistry:
    """Normalization + validation layer sitting between persistence and pipeline."""

    clubs: tuple[BasketballClub, ...] = field(factory=tuple, converter=tuple)
    alias_to_canonical: dict[str, str] = field(init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        mapping: dict[str, str] = {}
        for club in self.clubs:
            canonical = club.canonical_name.strip()
            if not canonical:
                continue
            for name in club.all_names():
                key = str(name).strip()
                if not key:
                    continue
                # If two clubs claim the same alias, prefer first definition.
                mapping.setdefault(key, canonical)

        object.__setattr__(self, "alias_to_canonical", mapping)

    def normalize_team_name(self, raw: str | None) -> str:
        if raw is None:
            return "Unknown"
        s = str(raw).strip()
        if not s:
            return "Unknown"
        return self.alias_to_canonical.get(s, s)

    def canonicalize_text(self, text: str) -> str:
        """Rewrite any embedded aliases inside a freeform string.

        This is used for backfilling stored JSON where team names can appear
        inside dict keys (e.g. colors maps) or in insight text.
        """

        out = text
        # Deterministic order: longer aliases first to reduce partial-overlap risk.
        items = sorted(self.alias_to_canonical.items(), key=lambda kv: len(kv[0]), reverse=True)
        for alias, canonical in items:
            if alias != canonical and alias in out:
                out = out.replace(alias, canonical)
        return out


def canonicalize_json(obj: Any, *, registry: ClubRegistry) -> Any:
    """Recursively canonicalize any strings found in a JSON-like structure.

    - Rewrites strings using registry.canonicalize_text() (substring replacement).
    - Also canonicalizes dict keys (important for `colors` maps keyed by team name).
    """

    if isinstance(obj, str):
        return registry.canonicalize_text(obj)

    if isinstance(obj, list):
        return [canonicalize_json(v, registry=registry) for v in obj]

    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            new_k = registry.canonicalize_text(k) if isinstance(k, str) else k
            new_v = canonicalize_json(v, registry=registry)
            if new_k in out:
                continue
            out[new_k] = new_v
        return out

    return obj


def load_clubs_from_yaml(path: Path = _CLUBS_YAML) -> tuple[BasketballClub, ...]:
    """Load club declarations from the YAML source of truth.

    Each entry's `registered_names_historically` becomes the aliases list.
    The `name` field is the canonical display name stored in processed JSONs.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    clubs: list[BasketballClub] = []
    for entry in raw.get("clubs", []):
        canonical = str(entry["name"]).strip()
        aliases = tuple(str(a).strip() for a in entry.get("registered_names_historically") or [])
        clubs.append(BasketballClub(canonical_name=canonical, aliases=aliases))
    return tuple(clubs)


# Default registry built from YAML source of truth.
DEFAULT_CLUBS: tuple[BasketballClub, ...] = load_clubs_from_yaml()
DEFAULT_REGISTRY = ClubRegistry(DEFAULT_CLUBS)


def normalize_team_name(raw: str | None, *, registry: ClubRegistry = DEFAULT_REGISTRY) -> str:
    return registry.normalize_team_name(raw)
