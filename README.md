# Euroleague Sankey Spike (MVP State)

Docker-first Euroleague possession-flow pipeline + static D3 viewer.

This README is onboarding-first: you can come back later and re-onboard quickly.

## 1) Project At A Glance

- Pipeline: Python scripts fetch Euroleague API data and build Sankey JSON.
- UI: static HTML + D3 (`poss-flow-map-multi-drilldown-real-data.html`).
- Data location:
  - raw API snapshots: `assets/`
  - processed viewer files: `assets/processed/`
- Primary UX entry points:
  - `index.html` (landing page)
  - `poss-flow-index.html` (game switcher + embedded viewer)
  - `poss-flow-map-multi-drilldown-real-data.html` (direct viewer)

## 2) Quick Start (Daily Loop)

### Build once

```bash
docker build -t euroleague-sankey .
```

### Generate demo data (primary command)

```bash
docker compose run --rm demo
```

What this does:

- Generates curated sample games.
- Writes processed files under `assets/processed/`.
- Refreshes `assets/processed/multi_drilldown_real_data.json` (default viewer file).
- Validates generated files.
- Rebuilds `assets/processed/games_manifest.json`.

### Serve and open UI

```bash
docker run --rm -p 8080:8080 -v "${PWD}:/app" -w /app python:3.12-slim python -m http.server 8080
```

Open:

- `http://localhost:8080/index.html`
- `http://localhost:8080/poss-flow-index.html`
- `http://localhost:8080/poss-flow-map-multi-drilldown-real-data.html`

## 3) Common Commands

### Single game pipeline + validation

```bash
docker run --rm -v "${PWD}:/app" -w /app euroleague-sankey \
  run_pipeline_and_validate --seasoncode E2021 --gamecode 54 \
  --output-dir /app/assets/processed \
  --output-pattern multi_drilldown_real_data_{seasoncode}_{gamecode}.json
```

### Multiple games pipeline + validation

```bash
docker run --rm -v "${PWD}:/app" -w /app euroleague-sankey \
  run_pipeline_and_validate --seasoncode E2021 --gamecode 54,55,56 \
  --output-dir /app/assets/processed \
  --output-pattern multi_drilldown_real_data_{seasoncode}_{gamecode}.json
```

### Sync a season range

```bash
docker compose run --rm season_sync
```

### Dry-run season sync

```bash
docker compose run --rm season_sync_dry
```

### Rebuild game manifest from existing processed files

```bash
docker run --rm -v "${PWD}:/app" -w /app euroleague-sankey \
  rebuild_manifest --seasoncode E2021 --output-dir /app/assets/processed
```

### Run test suite (network/API dependent)

```bash
docker compose run --rm tests
```

## 4) Data Flow

1. `build_from_euroleague_api.py`
   - fetches `PlaybyPlay`, `Points`, `Boxscore`
   - writes raw snapshots to `assets/`
   - infers possessions + builds Sankey-ready views
2. `pipeline_runner.py`
   - runs one/many games
   - writes processed JSON to `assets/processed/` by default
3. `validate_output.py`
   - lightweight schema/content checks
4. `season_sync.py`
   - batch sync over gamecode ranges
   - rebuilds `games_manifest.json`
5. UI pages
   - load processed files directly from disk (`assets/processed/...`)

## 5) App Config

### `BASKET_APP_FILE_STORE_URI`

- Purpose: base directory for persisted files.
- Default: `assets`
- Used by pipeline/entrypoint defaults.
- Effective processed output default: `${BASKET_APP_FILE_STORE_URI}/processed`
- Example:

```bash
docker run --rm \
  -e BASKET_APP_FILE_STORE_URI=/app/assets \
  -v "${PWD}:/app" -w /app euroleague-sankey demo
```

## 6) Current UI Notes (Prototype Behavior)

- `?typeZoomVariant=4`: standard 4-column type zoom rendering.
- `?typeZoomVariant=3`: 4 -> 3 transition prototype.
  - entering a type zoom from a non-type view uses the intentional push effect.
  - switching between type zooms (`halfcourt`, `transition`, `oreb`) now morphs in place (3 -> 3), no extra push.

## 7) Repo Pointers

- Runtime entrypoint: `entrypoint.py`
- Pipeline: `build_from_euroleague_api.py`, `pipeline_runner.py`
- Validation: `validate_output.py`
- Batch sync + manifest: `season_sync.py`
- Main viewer: `poss-flow-map-multi-drilldown-real-data.html`
- Landing/game switchers: `index.html`, `poss-flow-index.html`
- Team notes/spike context: `efforts/`, `epics_catalog.md`, `.github/copilot-instructions.md`
