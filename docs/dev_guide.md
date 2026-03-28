# Developer Guide

This guide defines how we keep fast experimentation while protecting the production surface.

## Branching Model

- `main`: production-safe codebase and source for public deploys.
- `dev`: integration branch for current iteration, UAT, and release candidates.
- `spike` (or `lab`): long-lived branch for ongoing experiments/POCs that must be preserved.
- optional `spike/*` branches: short-lived focused branches created from `spike` when needed.

Expected flow:

1. Build and preserve exploratory work in long-lived `spike`.
2. Cherry-pick or merge production-intended slices from `spike` into `dev`.
3. Run localhost UAT on `dev`.
4. Promote accepted state from `dev` to `main`.

## Product Surface Policy

Labs are first-class code, even if not exposed publicly yet.
That means experimental UI/modules can remain in `main` as long as production entry points stay curated.

Rules:

- Production entry pages expose only approved MVP journeys.
- Labs are accessible via preview entry pages/routes, not default production navigation.
- Feature flags/query params for labs are allowed in source, but production links should not surface non-MVP modes.

## Deploy Separation

Keep two deployment targets:

- `prod`: public MVP experience.
- `preview` (or `spike`): full feature/lab exploration from the long-lived experimental branch.

Packaging/deploy should use explicit allowlists:

- `prod` allowlist: only production-intended HTML/routes/assets.
- `preview` allowlist: production + lab pages.

Do not depend on branch name alone to determine surface area.

## UAT and Acceptance

Localhost UAT is a hard gate before `dev -> main`.

UAT output must be logged and triaged:

- `must-fix` issues block release.
- `later` issues are captured as refinement tasks.

After release, continue refinements on `dev` and promote in small batches.

## Onboarding Notes

When onboarding a new developer:

1. Explain production entry points vs lab entry points.
2. Explain `dev -> main` promotion and UAT gate.
3. Explain that labs are first-class source and should be maintained cleanly, not treated as throwaway code.

## Onboarding: Quick Start (for a "noob")

This section is a concise, copy-paste friendly checklist to get a new developer productive and to serve as the single source of truth for future onboarding updates. Keep this file up to date whenever you add pages, change build commands, or modify the data model.

- **Workspace entry points**:
	- `index.html` — Spike landing / tile wall used during dev/sprint exploration.
	- `poss-flow-index.html` — Game switcher + embedded viewer (iframe to the viewer).
	- `poss-flow-map-multi-drilldown-real-data.html` — Main Sankey viewer and the most feature-rich page (exploder, replay, labs).
	- `prod/` — Curated public payloads and entry pages intended for upload to S3 (the web bundler/CI should publish only this folder to the `prod` site).

- **What powers which feature**:
	- Flow Explode: implemented in `poss-flow-map-multi-drilldown-real-data.html` (see `renderExplodeFocus`, `buildRealPlayerMix`). Enabled by query param `?explodeLab=1`; we now default to enabled unless `?explodeLab=0` is present.
	- Live Replay: HUD + controls implemented in the viewer HTML/JS (elements with id `replay-*` and functions `startReplay`, `pauseReplay`, `resetReplay`). Enable with `?replayLab=1`.
	- Anchor Team / Game Explorer: `prod/game-explorer.html` orchestrates iframe loading and normalizes bundles for Anchor mode before passing them to the viewer.

- **Data locations**:
	- Raw snapshots: `assets/` (e.g. `raw_pbp_*.json`, `raw_box_*.json`).
	- Processed viewer files: `assets/processed/` (e.g. `multi_drilldown_real_data_E2021_54.json`).
	- Manifest: `assets/processed/games_manifest.json`.

- **Common local commands** (Docker-first):
	- Build image: `docker build -t euroleague-sankey .`
	- Generate curated demo data: `docker compose run --rm demo`
	- Serve a local static site (fast):
		```bash
		docker run --rm -p 8080:8080 -v "${PWD}:/app" -w /app python:3.12-slim python -m http.server 8080
		```
	- Run pipeline for specific game(s): see `README.md` examples using `run_pipeline_and_validate`.
	- Run validation tests: `docker compose run --rm tests` or run `validate_output.py` locally.

- **UAT flow (required before promoting `dev -> main`)**:
	1. `docker compose run --rm demo` (or run the pipeline for the candidate game set).
 2. Serve site and open `http://localhost:8080/prod/index.html` or `http://localhost:8080/prod/game-explorer.html`.
 3. Exercise core flow: game picker → Sankey base view → side panel KPIs → Flow Explode → Live Replay.
 4. Use `docs/uat_checklist.md` to record `must-fix` vs `later` items and capture sign-off.

- **Docs & process rules (always follow)**
	- If you change the data model (raw, processed, computed, or inferred fields), update `README.md` and `docs/data_model.schema.json` and add a short table entry in `README.md` under "Visualization Data Catalog" describing the change.
	- When adding any new environment variable, follow the project convention `BASKET_APP_*` and update `docker-compose.yml` plus the "App Config" section in `README.md` with purpose, default, and example use.
	- Keep `docs/uat_checklist.md` and this `docs/dev_guide.md` in sync with any UX or build flow changes — they are the canonical UAT and onboarding references.

	## Static Deployment: runtime config for viewer (S3 / CDN)

	For static `prod/` deployments the viewer needs to discover where processed JSON files live. The recommended approaches:

	- **Deployment-time config file (recommended)**: write a tiny `prod/config.js` that sets a global variable before the viewer loads:

	```html
	<script>window.BASKET_APP_FILE_STORE_URI = 'https://your-bucket.s3.amazonaws.com/assets';</script>
	```

	This is helpful when your CI/CD publishes the `prod/` folder to S3; the viewer will prefix processed file paths with this base.

	- **Ad-hoc via query param**: when opening the viewer you can pass `?fileBase=` to point at a custom base path for files. Example:

	```
	poss-flow-map-multi-drilldown-real-data.html?file=multi_drilldown_real_data_E2021_54.json&fileBase=https://your-bucket.s3.amazonaws.com/assets
	```

	Implementation notes:
	- The viewer also accepts `blob:` object URLs (created by the anchor-game normalizer) and will not modify them.
	- Keep `BASKET_APP_FILE_STORE_URI` consistent across pipeline defaults, Docker commands, and deployment scripts to avoid surprises.

- **Troubleshooting tips (fast fixes)**
	- Viewer shows stale JSON: refresh the page and confirm cache-buster param is present (viewer appends `?ts=`). If files still stale, rebuild demo and restart server.
	- Anchor mode iframe blank: ensure `prod/game-explorer.html` is passing a reachable URL/object URL to the iframe (we normalize bundles and sometimes create object URLs). If using blob URLs, open browser console to check for cross-origin or resource errors.

## Maintaining Onboarding Docs

Anyone touching UI entry points, data model, or CI/CD must update onboarding docs. Practical rule of thumb:

- If you change or add a public page under `prod/`, update `docs/dev_guide.md` and `README.md` with where it should appear and any required processed JSON filenames.
- If you change JSON shapes consumed by the UI, update `docs/data_inspection.md`, `docs/data_model.schema.json`, and `README.md` visualization catalog.
- Keep `docs/uat_checklist.md` up-to-date with triage logs and UAT sign-off records for each release.

If you want, I can now:
- Run `docker compose run --rm demo` and validate files were created, or
- Commit these docs updates (already patched) and open a PR, or
- Continue triage item #2 (anchor iframe blank) and implement a robust fix.

---

_Short-term note:_ This onboarding section is intentionally pragmatic and copy-paste friendly — treat `docs/dev_guide.md` as the first place to update when anything in the dev flow changes.

## Docs Practice: Copilot & Docs Maintenance

- When updating product-facing docs (`docs/product_specs.md`, `docs/uat_checklist.md`, `README.md`), add a one-line note in the PR description: "Docs updated — reason." This keeps changes discoverable.
- If you used GitHub Copilot to assist with code or docs changes, add `(assisted by GitHub Copilot)` to the PR description. This isn't required but helps reviewers know which parts were suggested by the tool.
- The engineer merging a change is responsible for ensuring `docs/product_specs.md` and `docs/uat_checklist.md` reflect the shipped behaviour before promoting `dev -> main`.
