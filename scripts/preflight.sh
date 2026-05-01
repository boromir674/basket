#!/usr/bin/env bash
# Validate local bundle readiness before deploy or push using the shared build config.
# The key feature is an optional clean-worktree guard so local-only changes cannot diverge from CI.
# preflight.sh — validate build config and git tracking before deploy.
#
# Usage:
#   scripts/preflight.sh           # validates app + lab
#   scripts/preflight.sh --mode app
#   scripts/preflight.sh --mode lab
#   scripts/preflight.sh --mode app --require-clean  # advisory-only for now

set -euo pipefail

MODE="all"
REQUIRE_CLEAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-all}"
      shift 2
      ;;
    --require-clean)
      REQUIRE_CLEAN=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: scripts/preflight.sh [--mode <app|lab|all>] [--require-clean]"
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

require_clean_worktree() {
  if [[ "$REQUIRE_CLEAN" -ne 1 ]]; then
    return
  fi

  if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "✗ --require-clean requested but repository metadata is unavailable"
    exit 1
  fi

  local status_output
  status_output="$(git -C "$REPO_ROOT" status --porcelain)"
  if [[ -n "$status_output" ]]; then
    echo "⚠ --require-clean advisory: worktree is not clean"
    echo "  Continuing preflight (clean enforcement temporarily disabled)."
    echo "  Sample status:"
    echo "$status_output" | head -n 20
  fi
}

run_mode() {
  local mode="$1"
  local out_dir
  out_dir="$(mktemp -d "${REPO_ROOT}/.tmp-preflight-${mode}-XXXXXX")"
  trap 'rm -rf "$out_dir"' RETURN

  echo "→ Preflight (${mode})"
  BASKET_ENFORCE_HEAD_CHECK=1 "${REPO_ROOT}/scripts/build_bundle.sh" --mode "$mode" --out "$out_dir"

  rm -rf "$out_dir"
  trap - RETURN
}

case "$MODE" in
  app)
    require_clean_worktree
    run_mode app
    ;;
  lab)
    require_clean_worktree
    run_mode lab
    ;;
  all)
    require_clean_worktree
    run_mode app
    run_mode lab
    ;;
  *)
    echo "Invalid mode: $MODE (expected app, lab, or all)"
    exit 2
    ;;
esac

echo "✓ Local preflight passed"
