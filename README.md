# Euroleague Sankey Spike (MVP State)

Docker-first Euroleague possession-flow pipeline + static D3 viewer.

This README is onboarding-first: you can come back later and re-onboard quickly.

## Cheatsheet

-> Get a whole season "prepared via latest data model": `make redo-season SEASON="E2025`

-> Normalize external Club names cause they might have variance: `make normalize-all-seasons` or `make normalize-season SEASON=E2025` 

-> Simulate Elo values from start to end of Seasons in DB: `make elo-auto`

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
./serve.sh          # default port 8080
PORT=9000 ./serve.sh
```

The script builds a `public/` bundle identical to what CI deploys, then serves it.
Open `http://localhost:8080/index.html` for the MVP surface.

> **Why `./serve.sh` instead of `python -m http.server` directly?**
> The deployed site is served from a flat `public/` directory (CI puts `prod/index.html`
> and `poss-flow-map-multi-drilldown-real-data.html` side-by-side with `assets/processed/`).
> Serving the repo root directly would put `index.html` one level below the assets, making
> all relative asset paths wrong. `serve.sh` mirrors the exact CI layout so paths are
> identical in every environment — no conditionals, no env vars, no surprises.

## 3) Common Commands

### Data ops (season sync, Elo, reporting)

See `docs/data_ops.md` for the noob-friendly, Docker-first workflow and the single unified CLI.

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

### Sync multiple seasons in one command

```bash
make sync-seasons SEASONS='E2022 E2023 E2024' START=1 END=380
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

### Recompute multi-season Elo automatically (when stale/missing)

```bash
make elo-auto DATA_DIR=/app/data
```

What `make elo-auto` does:

- scans stored files matching `multi_drilldown_real_data_E*_*.json`
- derives stored seasoncodes from first to last season
- verifies seasoncodes are consecutive
- compares against `elo_multiseason.json` coverage
- recomputes only if missing or stale (or when forced from CLI)

## 4) Data Flow

1. `build_from_euroleague_api.py`
   - fetches `PlaybyPlay`, `Points`, `Boxscore`
   - writes raw snapshots to `assets/`
   - infers possessions + builds Sankey-ready views
  - computes `meta.score_a/score_b/winner` from Boxscore (or a fallback sum of
    per-player points mapped via `players` -> team) so ELO can update
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

### Static viewer runtime config (S3 / CDN)

When deploying the static `prod/` content to S3 or CDN, the viewer can load processed JSON from a different base path than the repository `assets/` folder. Two options are supported:

- Add a small runtime config file that your bundler or deployment step writes into the published `prod/` folder, for example `prod/config.js`:

```html
<!-- prod/config.js -->
<script>window.BASKET_APP_FILE_STORE_URI = 'https://my-bucket.s3.amazonaws.com/assets';</script>
```

Include this `config.js` before the viewer HTML so the viewer honors the global `window.BASKET_APP_FILE_STORE_URI` at runtime.

- Or, for ad-hoc loads, append `?fileBase=` to the viewer URL when opening the page, for example:

```
http://my-host/poss-flow-map-multi-drilldown-real-data.html?file=multi_drilldown_real_data_E2021_54.json&fileBase=https://my-bucket.s3.amazonaws.com/assets
```

Notes:
- The viewer automatically preserves `blob:` object URLs (used by `prod/game-explorer.html` when normalizing bundles) and will not attempt to prefix or append cache-busters to them.
- Keep the `BASKET_APP_FILE_STORE_URI` convention aligned with pipeline defaults so dev -> prod paths are consistent.

## 6) Visualization Data Catalog

| Visualization / Module | Required Data (JSON) | Source Type | Notes |
|---|---|---|---|
| Main Sankey canvas | `views.<view>.nodes`, `views.<view>.links`, `views.<view>.starts`, `colors`, `meta` | `processed` + `computed` | Core layout is built from inferred possessions and grouped flow counters. |
| Side panel (context + KPIs + insights) | `views.<view>.title/desc/kpis/insights`, `meta` | `computed` + `modeled/inferred` | Insight text includes heuristic and optional auto-insight content. |
| Auto-insights panel rendering | `views.<view>.insights` strings prefixed with `AUTO:` | `computed` | Generated by `auto_insights.py` and merged into output JSON. |
| Shot profile / radar widgets | `views.top.links/nodes/starts`, `views.oreb.links`, `colors` | `computed` | Derived in browser from processed view links and event/points node conventions. |
| Flow explode lab (player mix) | `views.<view>.player_flows[\"source->target\"][]` with `player_id/player_name/team/poss` | `modeled/inferred` from raw API player fields | Uses real per-link player attribution when available; falls back to synthetic split only if missing. |
| Flow Index Q&A lab (narrative answers) | `views.<view>.player_flows`, `boxscore_players`, `views.<view>.links` | `modeled/inferred` + `raw API Boxscore` + `computed` | Combines flow contribution with boxscore context (`valuation`, `points`, `minutes`) for guided answers. |
| Live Replay Timeline lab | `views.<view>.links`, `views.top.links`, `meta` | `computed` | Simulated 0→40 replay: link reveal schedules + score interpolation from top-view points buckets. |
| Global player registry (optional utility) | `players` map (`player_id -> {name, team}`) | `processed` | Built from possession-level player attribution gathered from raw PBP rows. |
| Header ELO badge | `elo_{seasoncode}.json` (`ratings` map), `meta.team_a/team_b` | `computed` | Ratings derived from Boxscore totals; if Boxscore team names are codes, scores are summed via player points mapped through `players`. |
| Elo showcase timeline | `elo_multiseason.json` (`seasoncodes`, `history[].seasoncode`, `history[].season_label`, `history[].gamedate`, teams/scores/winner) | `computed` | UI enforces consecutive season selection and recomputes ratings in-browser from selected seasons only. Timeline x-axis uses fixture-style buckets (grouped by season + date). |

## 6.1) ELO Inputs (Why All-1500 Happens)

ELO updates only when `meta.score_a`, `meta.score_b`, or `meta.winner` are present.
If those are missing, ELO stays at the `initial_rating` (1500 by default) for all teams.

We now populate scores at build time using this priority:

1. Boxscore team totals (preferred): totals in `Boxscore.Stats` for each team.
2. Fallback: sum per-player points from `boxscore_players` and map each player ID
  to the full team name using `players`.

If both methods fail, the game is marked `outcome_unknown` and ELO will not move.

## 6.2) Multi-Season ELO (Consecutive Seasons)

Recommended flow:

```bash
make sync-seasons SEASONS='E2022 E2023 E2024' START=1 END=380
make normalize-season SEASON=E2022
make normalize-season SEASON=E2023
make normalize-season SEASON=E2024
make elo-auto DATA_DIR=/app/data
```

Manual multi-season build (explicit list):

```bash
make elo-multi SEASONS_CSV='E2022,E2023,E2024' DATA_DIR=/app/data
```

Notes:

- The UI prefers `elo_multiseason.json` when available.
- Season filter selections must remain consecutive (A,B,C allowed; A,B,D blocked).
- When replaying more than one season, the chart renders vertical divider lines at season boundaries.

## 7) Current UI Notes (Prototype Behavior)

- `?typeZoomVariant=4`: standard 4-column type zoom rendering.
- `?typeZoomVariant=3`: 4 -> 3 transition prototype.
  - entering a type zoom from a non-type view uses the intentional push effect.
  - switching between type zooms (`halfcourt`, `transition`, `oreb`) now morphs in place (3 -> 3), no extra push.
- `?explodeLab=1`: flow explode lab mode.
  - click a link to split it into player-colored micro-flows.
  - uses real `player_flows` data when present in processed JSON.
- `?xrayLab=1`: tactical X-Ray lab mode.
  - overlays a ghost baseline layer and shows branch deltas on hover.
  - current spike baseline is synthetic (derived from stage-pair structural averages in the active view).
- `?twinLab=1`: tactical Twin Sankey lab mode.
  - pseudo-3D dual-lane rendering (`current` lane and `reference` lane).
  - hover on one lane highlights the counterpart flow on the opposite lane with green/red over-under signal.
- `?flowIndexLab=1`: Flow Index Q&A lab mode.
  - adds guided question buttons that auto-focus branch states and player-mix details.
  - demo metric is a spike formula: `Flow Index = volume * expected_points` (tunable later).
- `?replayLab=1`: Live Replay Timeline mode.
  - HUD controls (`Play/Pause/Reset`) animate from minute 0 to 40.
  - links emerge/thicken over time and score grows in sync.

## 8) Repo Pointers

- `docs/decision_log.md`: tiny decision trail for high-impact changes that are easy to forget on revisit.

- Runtime entrypoint: `entrypoint.py`
- Pipeline: `build_from_euroleague_api.py`, `pipeline_runner.py`
- Validation: `validate_output.py`
- Batch sync + manifest: `season_sync.py`
- Main viewer: `poss-flow-map-multi-drilldown-real-data.html`
- Landing/game switchers: `index.html`, `poss-flow-index.html`
- Team notes/spike context: `efforts/`, `epics_catalog.md`, `.github/copilot-instructions.md`

## 9) Product Surface Separation (Prod vs Labs)

We treat visualization labs as first-class source code (similar to tests in backend repos).
Labs can live in `main`, but public production exposure is controlled by entry pages and deploy packaging.

- `main` branch: production-safe source of truth.
- `dev` branch: integration and pre-release hardening.
- `spike` (or `lab`) branch: long-lived experimental branch where POCs and exploratory UI can continue evolving.
- optional `spike/*` sub-branches can still be used for focused experiments before merging back to `spike`.

Deployment policy:

- Production deployment publishes only curated MVP pages/routes.
- Preview/spike deployment can expose full labs/features for exploration from the long-lived experimental branch.
- Do not rely on branch name alone to hide/show features; use explicit deploy allowlists for pages/assets.

Release gate:

- Localhost UAT is required before promoting `dev -> main`.
- UAT feedback is triaged into:
  - must-fix before release
  - post-release refinement backlog

See `docs/dev_guide.md` for day-to-day workflow details.

## 10) Surface Builds (Prod vs Preview)

Build deployment payloads without changing spike/demo source files:

```bash
scripts/build_surfaces.sh
```

Outputs:

- `dist/prod`: curated public MVP pages and required assets.
- `dist/preview`: spike/preview surface with full exploratory experience.

One-command local preparation:

```bash
scripts/publish_mvp.sh
```

UAT and launch docs:

- `docs/uat_checklist.md`
- `docs/launch_runbook_2h.md`
 - `docs/product_specs.md` — concise product-level MVP spec and acceptance criteria for the Unified Explorer.
