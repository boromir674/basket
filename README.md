# Euroleague Sankey Spike (MVP State)

Docker-first Euroleague possession-flow pipeline + static D3 viewer.

This README is onboarding-first: you can come back later and re-onboard quickly.

## Guide

<table>
  <thead>
    <tr>
      <th>Operation / Flow To Achieve</th>
      <th>Step-wise How-to</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Add a new season (end-to-end: raw + processed + manifest + normalization + Elo)</td>
      <td>
        <ol>
          <li>Full season sync (raw + multi + score_timeline + style_insights all at once): <code>make sync-season-full SEASON=E2026</code></li>
          <li>Normalize club/team names for that season: <code>make normalize-season SEASON=E2026</code></li>
          <li>Recompute Elo outputs for that season: <code>make elo SEASON=E2026</code></li>
          <li>Rerun ELO simulation <code>rm data/elo_multiseason.json && make elo-auto</code></li>
          <li>Rebuild the manifest so the frontend game switchers discover new games: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
          <li>Run a season report sanity check: <code>make report SEASON=E2026</code></li>
        </ol>
      </td>
    </tr>
      <td>Add newest published games in (current) Season (raw + processed + manifest + normalization + Elo)</td>
      <td>
        <ol>
          <li>Full season sync (raw + multi + score_timeline + style_insights all at once): <code>make sync-season-full SEASON=E2025</code></li>
          <li>Normalize club/team names for that season: <code>make normalize-season SEASON=E2025</code></li>
          <li>Recompute Elo outputs for that season: <code>make elo SEASON=E2025</code></li>
          <li>Rerun ELO simulation <code>rm data/elo_multiseason.json && make elo-auto</code></li>
          <li>Rebuild the manifest so the frontend game switchers discover new games: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
          <li>Run a season report sanity check: <code>make report SEASON=E2025</code></li>
        </ol>
      </td>
    </tr>
    <tr>
      <td>Backfill style insights only (already ingested seasons; no re-sync)</td>
      <td>
        <ol>
          <li>Run style insights only for target seasons (example older seasons): <code>for s in E2017 E2018 E2019 E2020; do docker compose run --rm ops style_insights --seasoncode $s --data-dir /app/data --output-dir /app/data; done</code></li>
          <li>(Optional) Rebuild manifest if downstream pages rely on fresh derived metadata snapshots: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
        </ol>
      </td>
    </tr>
    <tr>
      <td>After data model change: update ingested seasons in-place (all required updates)</td>
      <td>
        <ol>
          <li>Re-sync all relevant seasons so processed JSONs and score_timeline artifacts are rebuilt against current logic: <code>make sync-seasons SEASONS='E2017 E2018 E2019 E2020 E2021 E2022 E2023 E2024 E2025'</code></li>
          <li>Re-run normalization across all ingested seasons: <code>make normalize-all-seasons</code></li>
          <li>Re-run Elo from earliest to latest season to refresh Elo-derived fields: <code>make elo-auto</code></li>
          <li>Rebuild manifest for all seasons so frontend discovery metadata is aligned with regenerated data: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
          <li>Validate via reports across seasons: <code>make report</code></li>
        </ol>
      </td>
    </tr>
    <tr>
      <td>After adding a new normalization mapping: renormalize club names only (all data)</td>
      <td>
        <ol>
          <li>Apply club-name normalization in-place to all seasons: <code>make normalize-all-seasons</code></li>
          <li>Rebuild manifest so any normalized labels shown in lists/cards are updated consistently: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
          <li>Run reports to confirm expected naming and no unknown club leftovers: <code>make report</code></li>
        </ol>
      </td>
    </tr>
    <tr>
      <td>Elo algorithm changed in backend: rerun Elo simulation end-to-end and refresh Elo-dependent outputs</td>
      <td>
        <ol>
          <li>Recompute Elo from earliest to latest season: <code>make elo-auto</code></li>
          <li>Rebuild manifest so Elo badges/metadata used by frontend pages are refreshed: <code>docker-compose run --rm ops rebuild_manifest --all-seasons --output-dir /app/data</code></li>
          <li>Run reports to verify Elo availability and season-level consistency: <code>make report</code></li>
        </ol>
      </td>
    </tr>
  </tbody>
</table>

## Cheatsheet

-> Get a whole season "prepared via latest data model": `make redo-season SEASON="E2025`

-> Normalize external Club names cause they might have variance: `make normalize-all-seasons` or `make normalize-season SEASON=E2025` 

-> Sync full seasons without START/END args (auto-detected): `make sync-seasons SEASONS='E2022 E2023 E2024'`

-> Simulate Elo values from start to end of Seasons in DB: `make elo-auto`

-> Build Games Manifest (cheap way of frontend to discover content) from "current data": `docker-compose run --rm ops rebuild_manifest --all-seasons`

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

Shared builder used by local scripts and CI:

```bash
bash scripts/build_bundle.sh --mode app --out public
bash scripts/build_bundle.sh --mode lab --out public-lab
```

Run a local deploy preflight (config + git-tracking checks):

```bash
make preflight-app
# or
make preflight
# optional advisory mode: also print dirty-worktree sample (non-blocking for now)
make preflight-clean
```

> **Why `./serve.sh` instead of `python -m http.server` directly?**
> The deployed site is served from a flat `public/` directory (CI puts `prod/index.html`
> and `prod/game-flow-viewer.html` side-by-side with `assets/processed/`).
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
# All seasons with auto-detected game ranges (based on season code)
make sync-seasons SEASONS='E2022 E2023 E2024'

# Or specify custom START/END ranges
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

### Build score timeline artifacts from raw points

```bash
docker compose run --rm ops build_score_timeline --seasoncode E2025 --raw-dir /app/assets --output-dir /app/data
```

### Build team style insights (consistency + adaptability)

```bash
docker compose run --rm ops style_insights --seasoncode E2025 --data-dir /app/data --output-dir /app/data
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

Artifact families in current MVP:

- `raw`: `raw_pbp_*`, `raw_pts_*`, `raw_box_*`
- `multi`: `multi_drilldown_real_data_*`
- `score_timeline`: `score_timeline_*`
- `style_insights`: `style_insights_*`

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
5. `style_insights.py`
  - computes season-level style consistency/adaptability from `score_timeline_*`
  - writes `style_insights_<season>.json`
6. UI pages
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

When deploying static content, both build-time file requirements and runtime asset settings come from `config/build_config.jsonc`. The build emits those runtime settings into `prod/runtime-config.js` during `scripts/build_bundle.sh`.

This means production pages (`index`, `game-explorer`, `game-flow-viewer`, score pages, Elo, style insights) resolve manifests and assets from the same config values, not page-local hardcoded paths.

To point to remote storage (S3/CDN), two options are supported:

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

### Local deploy guard (missing tracked JSON prevention)

If required JSON files exist locally but are ignored by git, deploys can fail with file-not-found in production. The shared bundle builder now validates that all config-required files are already present in `HEAD`, not merely staged in the index.

- `make preflight-app` checks app bundle config + tracking
- `make preflight` checks app + lab
- `make preflight-clean` checks app bundle config + tracking and also prints dirty-worktree sample status (advisory only for now)
- `make install-hooks` installs a `pre-push` hook that runs `preflight-app --require-clean`
- CI (`.github/workflows/build-bundle.yml`) now runs default preflight (`scripts/preflight.sh`) before the bundle build step.

Guarantee scope:

- Deploys already build from a fresh CI checkout, so files that were never committed or pushed are not present in CI and cannot silently ship.
- Required build-config files are now validated for existence, manifest coverage, raw timeline coverage, and presence in `HEAD`.
- Score-diff families (`score-diff`, `score-d52`, and v2/full-paint variants) are explicitly covered through required `raw_pts` and `score_timeline` dataset checks in build config.
- To also catch the broader "local looked fine because my worktree had extra changes" case, use the clean-worktree guard (`make preflight-clean`) or install the hook.
- This still only protects assets and pages covered by `config/build_config.jsonc`. If a future surface is added and not added to the build config, it is outside this guarantee.

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
| App Game Viewer embedded cone (below Sankey) | `raw_pts_{season}_{game}.json`, `games_manifest.json` | `raw API` + `computed` in-browser | Per-selected-game score differential cone uses timeline rows from raw points feed and must exist for every manifest game. |
| Global player registry (optional utility) | `players` map (`player_id -> {name, team}`) | `processed` | Built from possession-level player attribution gathered from raw PBP rows. |
| Header ELO badge | `elo_{seasoncode}.json` (`ratings` map), `meta.team_a/team_b` | `computed` | Ratings derived from Boxscore totals; if Boxscore team names are codes, scores are summed via player points mapped through `players`. |
| Elo showcase timeline | `elo_multiseason.json` (`seasoncodes`, `history[].seasoncode`, `history[].season_label`, `history[].gamedate`, teams/scores/winner) | `computed` | UI enforces consecutive season selection and recomputes ratings in-browser from selected seasons only. Timeline x-axis uses fixture-style buckets (grouped by season + date). |
| Style Insights page | `style_insights_{season}.json` (`teams[].consistency_score`, `teams[].adaptability_score`, `teams[].evidence.consistency[]`, `teams[].evidence.adaptability[]`) | `computed` + `modeled/inferred` from timeline events | Spotlight cards auto-select top teams and open modal evidence; representative games are deterministic and include reason tags plus mix/shift summaries. |
| 2D Shot Style Map Lab | `raw_pts_{season}_{game}.json`, `raw_box_{season}_{game}.json`, `games_manifest.json` | `raw API` + `computed` in-browser | Bins half-court coordinates and computes attempts/100, points/attempt, contribution/100, and league-bin baseline deltas with optional filters (team/opponent/home-away/phase/possession type). |

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

## 6.3) Elo First-Run Onboarding (Mobile-First UX)

The Elo showcase page now includes a lightweight first-run modal that explains Elo in under 20 seconds:

- **What is Elo?** Plain-language definition: "Elo is a strength rating that updates after each game based on result and opponent strength."
- **Why it matters?** "Higher Elo means stronger recent performance relative to league peers."
- **How to use?** "Use season buttons to filter, then hit Play to watch Elo evolve fixture-by-fixture."

**Behavior:**
- Modal appears once per browser (localStorage-persisted dismissal).
- All visible seasons are preselected by default (enabling immediate multi-season replay).
- Dismissal is stored in `elo_onboarding_dismissed` localStorage key.
- Tap/click the backdrop or "Got it" button to close.

**Access:**
- Entry point: `prod/elo.html` (plain, no query params) triggers onboarding on first visit.
- Lab tile: "Elo First-Run Onboarding" in `lab/index.html` shortcuts to the onboarding experience.
- Skip onboarding: Any query param (e.g., `?seasoncodes=E2025`) or revisit after dismissal will skip the modal.

## 6.4) Re-seed ELO From A Different Initial Value

When you want to recompute Elo from a different starting value (instead of 1500), use this quick flow:

1. Recompute Elo in the pipeline with an explicit seed via `--initial-rating`.

```bash
docker compose run --rm ops compute_elo --auto \
  --output-dir /app/data \
  --output-name elo_multiseason.json \
  --initial-rating 1400
```

2. Update the frontend Elo replay fallback in both showcase pages if you want a matching UI default for payloads that do not provide `initial_rating`.
  - `public/elo.html` around `buildDerivedTimeline()` (`const v = (elo && typeof elo.initial_rating === 'number') ? elo.initial_rating : 1500;`)
  - `prod/elo.html` same location and logic

3. Rebuild and verify the result end-to-end.
  - Run: `make test ARGS="-vvs -ra -k elo"`
  - Open the Elo page and confirm baseline values reflect your new seed.

## 7) Current UI Notes (Prototype Behavior)

- `?typeZoomVariant=4`: standard 4-column type zoom rendering.
- `?typeZoomVariant=3`: 4 -> 3 transition prototype.
  - entering a type zoom from a non-type view uses the intentional push effect.
  - switching between type zooms (`halfcourt`, `transition`, `oreb`) now morphs in place (3 -> 3), no extra push.
- `Made 2 breakdown` and `Made 3 breakdown` subviews were removed from navigation in both lab and prod hosts.
  - direct navigation requests for `made2`/`made3` are normalized back to `top`.
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
- Main viewer: `prod/game-flow-viewer.html`
- Landing/game switchers: `index.html`, `lab/game-flow-switcher.html`, `prod/game-explorer.html`
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

### Games Manifest

Canonical source: `data/games_manifest.json` (copied to `public/assets/processed/` and `dist/` by build scripts).
To rebuild for all seasons: `python entrypoint.py rebuild_manifest --all-seasons --output-dir assets/processed`.
Single-season rebuild (backwards compatible): `python entrypoint.py rebuild_manifest --seasoncode E2025`.
Note: the manifest currently only contains E2025 — run the all-seasons rebuild after any multi-season sync.

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

## 11) E2E Testing (Cypress)

Cypress specs live in `e2e/cypress/e2e/` and cover MVP interaction flows:

### Run E2E tests

```bash
# Run all E2E tests in interactive mode
cd e2e && npm test

# Run specific spec
npm test -- cypress/e2e/elo-season-preselect.cy.js

# Run headless (CI mode)
npm run test:headless
```

### Key specs

- **`elo-season-preselect.cy.js`** — Verifies Elo onboarding UX:
  - All available seasons are preselected on first load
  - Onboarding modal appears and has dismiss button
  - Dismissal is persisted across page reloads
  - Rank table populates correctly with multi-season data

**Design goal:** Tests are written with GIVEN/WHEN/THEN comments for clarity and serve as executable specification of expected MVP behavior.
