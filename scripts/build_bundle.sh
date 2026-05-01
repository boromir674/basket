#!/usr/bin/env bash
# build_bundle.sh — shared bundle builder for app and lab surfaces.
#
# Usage:
#   scripts/build_bundle.sh --mode app --out public
#   scripts/build_bundle.sh --mode lab --out public-lab

set -euo pipefail

MODE="app"
OUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: scripts/build_bundle.sh --mode <app|lab> --out <dir>"
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "$MODE" != "app" && "$MODE" != "lab" ]]; then
  echo "Invalid mode: $MODE (expected app or lab)"
  exit 2
fi

if [[ -z "$OUT_DIR" ]]; then
  if [[ "$MODE" == "app" ]]; then
    OUT_DIR="public"
  else
    OUT_DIR="public-lab"
  fi
fi

cd "$REPO_ROOT"

# Read build contract and validate required files exist
echo "→ Validating build contract from config/build_contract.json..."
CONTRACT_FILE="config/build_contract.json"
if [[ ! -f "$CONTRACT_FILE" ]]; then
  echo "✗ Build contract not found: $CONTRACT_FILE"
  exit 1
fi

# Check for required static files
validate_required_files() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "✗ Required file missing: $file"
    return 1
  fi
}

# Contract validation: ensure games_manifest and at least one per-game sankey file exist
if ! validate_required_files "data/games_manifest.json"; then
  echo "✗ Build contract violation: data/games_manifest.json is required"
  exit 1
fi

# Count available per-game sankey files
game_files_found=$(ls data/multi_drilldown_real_data_E*.json 2>/dev/null | wc -l || echo 0)
if [[ "$game_files_found" -eq 0 ]]; then
  echo "✗ Build contract violation: No per-game files found (data/multi_drilldown_real_data_E*.json)"
  echo "   The pipeline must generate these files before bundling."
  exit 1
fi
echo "✓ Contract validated (${game_files_found} per-game sankey files found)"

echo "→ Building ${OUT_DIR}/ bundle (mode=${MODE})..."
rm -rf "$OUT_DIR"

if [[ "$MODE" == "app" ]]; then
  mkdir -p "$OUT_DIR/assets/processed"
  mkdir -p "$OUT_DIR/src"

  cp prod/index.html                             "$OUT_DIR/"
  cp prod/game-explorer.html                     "$OUT_DIR/"
  cp prod/elo.html                               "$OUT_DIR/"
  cp prod/score-diff.html                        "$OUT_DIR/"
  cp prod/score-d52.html                         "$OUT_DIR/"
  cp prod/score-diff-v2.html                     "$OUT_DIR/"
  cp prod/score-d52-v2.html                      "$OUT_DIR/"
  cp prod/style-insights.html                    "$OUT_DIR/"
  cp prod/score-chart.js                         "$OUT_DIR/"

  cp prod/game-flow-viewer.html                  "$OUT_DIR/"
  cp src/sankey-renderer.js                      "$OUT_DIR/src/"
else
  mkdir -p "$OUT_DIR/assets/processed" "$OUT_DIR/prod" "$OUT_DIR/src"

  cp -r ./lab "$OUT_DIR/lab"

  cp prod/index.html                             "$OUT_DIR/prod/"
  cp prod/game-explorer.html                     "$OUT_DIR/prod/"
  cp prod/elo.html                               "$OUT_DIR/prod/"
  cp prod/score-diff.html                        "$OUT_DIR/prod/"
  cp prod/score-d52.html                         "$OUT_DIR/prod/"
  cp prod/score-diff-v2.html                     "$OUT_DIR/prod/"
  cp prod/score-d52-v2.html                      "$OUT_DIR/prod/"
  cp prod/style-insights.html                    "$OUT_DIR/prod/"
  cp prod/score-chart.js                         "$OUT_DIR/prod/"

  cp prod/game-flow-viewer.html                  "$OUT_DIR/prod/"
  cp lab/game-flow-switcher.html                 "$OUT_DIR/lab/"
  cp src/sankey-renderer.js                      "$OUT_DIR/src/"
fi

if ls data/*.json 1>/dev/null 2>&1; then
  cp data/*.json "$OUT_DIR/assets/processed/"
  echo "✓ Data files copied from data/"
else
  echo "⚠  No data in data/"
fi

mkdir -p "$OUT_DIR/assets"
if ls assets/raw_pts_*.json 1>/dev/null 2>&1; then
  cp assets/raw_pts_*.json "$OUT_DIR/assets/"
  echo "✓ raw_pts files copied"
else
  echo "⚠  No raw_pts_*.json in assets/"
fi

if [[ "$MODE" == "lab" ]]; then
  if ls assets/raw_box_*.json 1>/dev/null 2>&1; then
    cp assets/raw_box_*.json "$OUT_DIR/assets/"
    echo "✓ raw_box files copied"
  else
    echo "⚠  No raw_box_*.json in assets/"
  fi
fi

echo ""
echo "✓ Bundle ready: ${OUT_DIR}/"
echo "  (Built per config/build_contract.json, mode=${MODE})"
echo ""