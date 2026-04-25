"""TDD for ClubRegistry normalization.

Fixture data derived from real ELO multi-season output (E2022-E2025) which
exposed 28 apparent teams where only ~22 distinct clubs exist.
"""
from __future__ import annotations

import pytest
from basket.clubs import DEFAULT_REGISTRY, ClubRegistry, BasketballClub


# ---------------------------------------------------------------------------
# Fixture: raw API names that should resolve to a canonical club
# (alias, expected_canonical)
# ---------------------------------------------------------------------------
ALIAS_CASES = [
    # Baskonia sponsor drift
    ("Cazoo Baskonia Vitoria-Gasteiz",   "Baskonia Vitoria-Gasteiz"),
    ("Cazoo",                             "Baskonia Vitoria-Gasteiz"),
    ("Baskonia Vitoria-Gasteiz",          "Baskonia Vitoria-Gasteiz"),  # canonical pass-through

    # Red Star Belgrade sponsor drift
    ("Crvena Zvezda mts Belgrade",        "Crvena Zvezda Belgrade"),
    ("Crvena Zvezda Belgrade",            "Crvena Zvezda Belgrade"),     # canonical pass-through

    # Maccabi Tel Aviv sponsor drift
    ("Maccabi Playtika Tel Aviv",         "Maccabi Tel Aviv"),
    ("Maccabi Rapyd Tel Aviv",            "Maccabi Tel Aviv"),

    # Panathinaikos sponsor drift
    ("Panathinaikos AKTOR Athens",        "Panathinaikos Athens"),
    ("Panathinaikos Athens",              "Panathinaikos Athens"),       # canonical pass-through

    # Virtus Bologna sponsor drift
    ("Virtus Segafredo Bologna",          "Virtus Bologna"),
    ("Virtus Bologna",                    "Virtus Bologna"),             # canonical pass-through

    # LDLC ASVEL truncated API name
    ("LDLC",                              "LDLC ASVEL Villeurbanne"),
    ("LDLC ASVEL Villeurbanne",           "LDLC ASVEL Villeurbanne"),   # canonical pass-through
]

# Names that have no alias (stable names that should pass through unchanged)
STABLE_NAMES = [
    "Olympiacos Piraeus",
    "Real Madrid",
    "Valencia Basket",
    "Fenerbahce Beko Istanbul",
    "Zalgiris Kaunas",
    "AS Monaco",
    "Hapoel IBI Tel Aviv",
    "FC Barcelona",
    "Dubai Basketball",
    "Partizan Mozzart Bet Belgrade",
    "FC Bayern Munich",
    "Paris Basketball",
    "EA7 Emporio Armani Milan",
    "Anadolu Efes Istanbul",
    "ALBA Berlin",
]

# After full normalization the 28-name ELO list should collapse to this many clubs
EXPECTED_DISTINCT_CLUBS = 24


@pytest.mark.parametrize("raw,expected", ALIAS_CASES)
def test_normalize_alias(raw, expected):
    assert DEFAULT_REGISTRY.normalize_team_name(raw) == expected


@pytest.mark.parametrize("name", STABLE_NAMES)
def test_stable_names_pass_through(name):
    assert DEFAULT_REGISTRY.normalize_team_name(name) == name


def test_none_returns_unknown():
    assert DEFAULT_REGISTRY.normalize_team_name(None) == "Unknown"


def test_empty_string_returns_unknown():
    assert DEFAULT_REGISTRY.normalize_team_name("") == "Unknown"


def test_elo_28_names_collapse_to_expected_distinct_clubs():
    """The 31 team names (28 from E2022-E2025 ELO + 3 others) should collapse to expected distinct clubs."""
    raw_elo_names = [
        "Olympiacos Piraeus",
        "Real Madrid",
        "Valencia Basket",
        "Fenerbahce Beko Istanbul",
        "Zalgiris Kaunas",
        "AS Monaco",
        "Panathinaikos AKTOR Athens",
        "Hapoel IBI Tel Aviv",
        "FC Barcelona",
        "Crvena Zvezda Belgrade",
        "Dubai Basketball",
        "Crvena Zvezda mts Belgrade",
        "Partizan Mozzart Bet Belgrade",
        "Maccabi Rapyd Tel Aviv",
        "Cazoo Baskonia Vitoria-Gasteiz",
        "FC Bayern Munich",
        "LDLC",
        "Cazoo",
        "Paris Basketball",
        "EA7 Emporio Armani Milan",
        "Panathinaikos Athens",
        "Baskonia Vitoria-Gasteiz",
        "Maccabi Playtika Tel Aviv",
        "Anadolu Efes Istanbul",
        "Virtus Bologna",
        "Virtus Segafredo Bologna",
        "LDLC ASVEL Villeurbanne",
        "ALBA Berlin",
        "CSKA Moscow",
        "UNICS Kazan",
        "Zenit St Petersburg",
    ]
    assert len(raw_elo_names) == 31, "fixture sanity check"

    normalized = {DEFAULT_REGISTRY.normalize_team_name(n) for n in raw_elo_names}
    assert len(normalized) == EXPECTED_DISTINCT_CLUBS, (
        f"Expected {EXPECTED_DISTINCT_CLUBS} distinct clubs, got {len(normalized)}: {sorted(normalized)}"
    )


def test_registry_duplicate_alias_prefers_first_definition():
    """If two clubs claim the same alias, first definition wins (no silent clobber)."""
    c1 = BasketballClub(canonical_name="Club A", aliases=("Shared Alias",))
    c2 = BasketballClub(canonical_name="Club B", aliases=("Shared Alias",))
    reg = ClubRegistry((c1, c2))
    assert reg.normalize_team_name("Shared Alias") == "Club A"


def test_yaml_loads_and_covers_all_known_clubs():
    """YAML source of truth must load cleanly and contain all 24 expected clubs."""
    assert len(DEFAULT_REGISTRY.clubs) == 24


def test_club_id_derived_from_canonical_name():
    c = BasketballClub(canonical_name="Real Madrid")
    assert c.id == "real-madrid"

    c2 = BasketballClub(canonical_name="LDLC ASVEL Villeurbanne")
    assert c2.id == "ldlc-asvel-villeurbanne"

    c3 = BasketballClub(canonical_name="Crvena Zvezda Belgrade")
    assert c3.id == "crvena-zvezda-belgrade"
