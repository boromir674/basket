# Data Ops (Docker CLI) — Noob Guide

This project is **Docker-first**. Treat `entrypoint.py` as the single CLI for:

1) fetching/syncing/building season game JSONs
2) normalizing/fixing stored JSONs (canonical team names)
3) computing Elo outputs
4) reporting season stats (games + teams)

All commands below run via Docker Compose.

## TL;DR

Prepare a season end-to-end (sync → normalize → Elo → manifest → report):

```bash
make prepare-season SEASON=E2025 START=1 END=200
```

Prepare multiple consecutive seasons quickly:

```bash
make sync-seasons SEASONS='E2022 E2023 E2024' START=1 END=380
```

See the report:

```bash
make report SEASON=E2025
```

## Where data lives

- Season “database” JSONs live in `./data/` (mounted in containers as `/app/data`).
- Raw API snapshots live in `./assets/` (mounted as `/app/assets`).

## Step-by-step: fill a season (main data model)

1) Sync/build the season JSONs into `data/`:

```bash
make sync-season SEASON=E2025 START=1 END=200
```

Faster (concurrent) sync:

```bash
make sync-season SEASON=E2025 START=1 END=380 CONCURRENCY=8 PRESSURE=1.0
```

Notes:
- `CONCURRENCY` controls max parallel game builds (threads). Default is conservative (`1`).
- `PRESSURE` is a float in `[0,1]` that scales effective concurrency; on HTTP 429 the sync backs off and reduces pressure.
- The sync can optionally do a sequential retry pass for failed gamecodes.

Logging:
- By default, `sync_season` logs **INFO** to the terminal.
- It also writes a **DEBUG** log file under `./data/logs/` (inside the container: `/app/data/logs/`).
- To see DEBUG logs on the terminal:

```bash
make sync-season SEASON=E2025 START=1 END=380 CONCURRENCY=8 PRESSURE=1.0 LOG_LEVEL=DEBUG
```

2) Normalize/fix team-name aliases in the stored JSONs:

```bash
make normalize-season SEASON=E2025
```

## Sponsor drift / club-name normalization

Problem: upstream team labels can change mid-season (sponsor/name drift), which can split one club into multiple “teams” in our stored JSONs.

This repo handles it in two places:

1) In-pipeline normalization (future data)
- During API fetch/build, team names are canonicalized through the basket library component in `src/basket/clubs.py`.

2) Post-pipeline backfill (existing data)
- Run `make normalize-season SEASON=E2025` to rewrite stored season JSONs in-place, including occurrences inside:
	- `meta.team_a` / `meta.team_b`
	- `colors` keys
	- insight text

### How to add new mappings (developer workflow)

Edit the registry in `src/basket/clubs.py`:

- Add a `BasketballClub(canonical_name=..., aliases=(...))` entry under `DEFAULT_CLUBS`.
- Use the stable club identity as `canonical_name` (prefer sponsor-less when possible).
- Put any known upstream variants under `aliases`.

Then backfill and validate:

```bash
make normalize-season SEASON=E2025
make report SEASON=E2025
```

3) Compute Elo for that season (writes `elo_{seasoncode}.json` into `data/`):

```bash
make elo SEASON=E2025
```

3b) Compute multi-season Elo (explicit season list):

```bash
make elo-multi SEASONS_CSV='E2022,E2023,E2024'
```

3c) Auto recompute multi-season Elo only when stale/missing:

```bash
make elo-auto
```

`make elo-auto` scans stored season bundles, checks consecutive coverage, and ensures
`elo_multiseason.json` spans the full stored consecutive range.

4) Print a report (games + distinct teams):

```bash
make report SEASON=E2025
```

## One-shot: get everything ready

```bash
make prepare-season SEASON=E2025 START=1 END=200
```

This runs:
- `sync_season`
- `normalize_season_data`
- `compute_elo`
- `rebuild_manifest`
- `report_season`

## Direct CLI (no Makefile)

All Make targets are thin wrappers around:

```bash
docker-compose run --rm ops <command> [args...]
```

For example:

```bash
docker-compose run --rm ops report_season --seasoncode E2025 --data-dir /app/data
```
