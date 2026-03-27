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
