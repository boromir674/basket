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

if ! command -v jq >/dev/null 2>&1; then
  echo "✗ jq is required to read ${CONTRACT_FILE}"
  exit 1
fi

MODE_CONFIG_JSON="$(jq -c --arg mode "$MODE" '
  def merged_mode($m):
  .modes[$m] as $cur
  | (if (($cur.inherits_from? // "") != "") then merged_mode($cur.inherits_from) else {} end) as $parent
  | {
    required_static_files: (($parent.required_static_files // {}) + ($cur.required_static_files // {})),
    required_per_game_files: (($parent.required_per_game_files // {}) + ($cur.required_per_game_files // {})),
    additional_required_per_game_files: (($parent.additional_required_per_game_files // {}) + ($cur.additional_required_per_game_files // {})),
    html_pages: (((($parent.html_pages // []) + ($cur.html_pages // [])) | unique)),
    js_modules: (((($parent.js_modules // []) + ($cur.js_modules // [])) | unique)),
    copy_directories: (((($parent.copy_directories // []) + ($cur.copy_directories // [])) | unique)),
    optional_asset_globs: (($parent.optional_asset_globs // {}) + ($cur.optional_asset_globs // {}))
  };
  {
  processed_data_dir: (.sources.processed_data_dir // "data"),
  raw_data_dir: (.sources.raw_data_dir // "assets"),
  mode: merged_mode($mode)
  }
' "$CONTRACT_FILE")"

PROCESSED_DATA_DIR="$(jq -r '.processed_data_dir' <<<"$MODE_CONFIG_JSON")"
RAW_DATA_DIR="$(jq -r '.raw_data_dir' <<<"$MODE_CONFIG_JSON")"
mapfile -t REQUIRED_STATIC_FILES < <(jq -r '.mode.required_static_files | keys[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t REQUIRED_PER_GAME_PATTERNS < <(jq -r '((.mode.required_per_game_files // {} | keys) + (.mode.additional_required_per_game_files // {} | keys))[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t HTML_PAGES < <(jq -r '.mode.html_pages[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t JS_MODULES < <(jq -r '.mode.js_modules[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t COPY_DIRECTORIES < <(jq -r '.mode.copy_directories[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t OPTIONAL_ASSET_GLOBS < <(jq -r '.mode.optional_asset_globs | keys[]?' <<<"$MODE_CONFIG_JSON")

# Derive runtime manifest filename from required_static_files so the contract
# has a single declaration of this requirement.
MANIFEST_FILE="$(jq -r '
  [(.mode.required_static_files | keys[]?)
   | select(test("(^|/)games_manifest\\.json$"))
   | split("/") | last][0] // "games_manifest.json"
' <<<"$MODE_CONFIG_JSON")"

for req_file in "${REQUIRED_STATIC_FILES[@]}"; do
  if [[ ! -f "$req_file" ]]; then
    echo "✗ Build contract violation: required file missing: $req_file"
    exit 1
  fi
done

game_files_found=0
REQUIRE_RAW_PTS=0
for pattern in "${REQUIRED_PER_GAME_PATTERNS[@]}"; do
  if [[ "$pattern" == *"/raw_pts_E*.json" || "$pattern" == "raw_pts_E*.json" ]]; then
    REQUIRE_RAW_PTS=1
  fi
  count=$(compgen -G "$pattern" | wc -l || true)
  if [[ "$count" -eq 0 ]]; then
    echo "✗ Build contract violation: no files found for pattern: $pattern"
    echo "  Pipeline must generate these outputs before bundling."
    exit 1
  fi
  game_files_found=$((game_files_found + count))
done

MANIFEST_PATH="${PROCESSED_DATA_DIR}/${MANIFEST_FILE}"
if [[ -f "$MANIFEST_PATH" ]]; then
  echo "→ Validating manifest coverage from ${MANIFEST_PATH}..."
  coverage_report="$(python3 - "$MANIFEST_PATH" "$PROCESSED_DATA_DIR" <<'PY'
import json
import os
import sys

manifest_path = sys.argv[1]
data_dir = sys.argv[2]

with open(manifest_path, encoding="utf-8") as f:
    manifest = json.load(f)

missing = []
for row in manifest:
    fname = row.get("file")
    if not fname:
        continue
    fpath = os.path.join(data_dir, fname)
    if not os.path.isfile(fpath):
        missing.append(fname)

print(f"manifest_entries={len(manifest)}")
print(f"missing_entries={len(missing)}")
if missing:
    print("missing_sample=" + ", ".join(missing[:10]))
PY
)"

  manifest_entries="$(echo "$coverage_report" | awk -F= '/^manifest_entries=/{print $2}')"
  missing_entries="$(echo "$coverage_report" | awk -F= '/^missing_entries=/{print $2}')"
  missing_sample="$(echo "$coverage_report" | awk -F= '/^missing_sample=/{print $2}')"

  if [[ "$missing_entries" != "0" ]]; then
    echo "✗ Build contract violation: manifest references ${missing_entries} missing per-game files"
    if [[ -n "$missing_sample" ]]; then
      echo "  Missing sample: ${missing_sample}"
    fi
    echo "  Fix data/ or regenerate manifest before bundling."
    exit 1
  fi
  echo "✓ Manifest coverage validated (${manifest_entries} entries, 0 missing files)"

  if [[ "$REQUIRE_RAW_PTS" -eq 1 ]]; then
    echo "→ Validating raw_pts timeline coverage from manifest..."
    raw_pts_report="$(python3 - "$MANIFEST_PATH" "$RAW_DATA_DIR" <<'PY'
import json
import os
import sys

manifest_path = sys.argv[1]
raw_data_dir = sys.argv[2]

with open(manifest_path, encoding="utf-8") as f:
    manifest = json.load(f)

missing = []
for row in manifest:
    season = row.get("seasoncode")
    gamecode = row.get("gamecode")
    if not season or gamecode is None:
        continue
    fname = f"raw_pts_{season}_{gamecode}.json"
    fpath = os.path.join(raw_data_dir, fname)
    if not os.path.isfile(fpath):
        missing.append(fname)

print(f"missing_raw_pts={len(missing)}")
if missing:
    print("missing_raw_pts_sample=" + ", ".join(missing[:10]))
PY
)"

    missing_raw_pts="$(echo "$raw_pts_report" | awk -F= '/^missing_raw_pts=/{print $2}')"
    missing_raw_pts_sample="$(echo "$raw_pts_report" | awk -F= '/^missing_raw_pts_sample=/{print $2}')"

    if [[ "$missing_raw_pts" != "0" ]]; then
      echo "✗ Build contract violation: manifest references ${missing_raw_pts} games without raw_pts timeline JSON"
      if [[ -n "$missing_raw_pts_sample" ]]; then
        echo "  Missing raw_pts sample: ${missing_raw_pts_sample}"
      fi
      echo "  Cone chart requires raw_pts_{season}_{game}.json for each game in manifest."
      exit 1
    fi
    echo "✓ raw_pts coverage validated (0 missing files)"
  fi
fi

echo "✓ Contract validated (${game_files_found} files found across required per-game patterns)"

echo "→ Building ${OUT_DIR}/ bundle (mode=${MODE})..."
rm -rf "$OUT_DIR"

if [[ "$MODE" == "app" ]]; then
  mkdir -p "$OUT_DIR/assets/processed" "$OUT_DIR/src" "$OUT_DIR/lab"
else
  mkdir -p "$OUT_DIR/assets/processed" "$OUT_DIR/prod" "$OUT_DIR/src" "$OUT_DIR/lab"
fi

copy_contract_file() {
  local source_path="$1"
  local destination_dir="$OUT_DIR"
  local destination_file=""

  if [[ "$MODE" == "app" ]]; then
    if [[ "$source_path" == prod/* ]]; then
      destination_dir="$OUT_DIR"
    elif [[ "$source_path" == src/* ]]; then
      destination_dir="$OUT_DIR/src"
    elif [[ "$source_path" == lab/* ]]; then
      destination_dir="$OUT_DIR/lab"
    fi
  else
    if [[ "$source_path" == prod/* ]]; then
      destination_dir="$OUT_DIR/prod"
    elif [[ "$source_path" == src/* ]]; then
      destination_dir="$OUT_DIR/src"
    elif [[ "$source_path" == lab/* ]]; then
      destination_dir="$OUT_DIR/lab"
    fi
  fi

  mkdir -p "$destination_dir"
  destination_file="$destination_dir/$(basename "$source_path")"
  cp "$source_path" "$destination_file"

  # Inject runtime manifest filename from contract into HTML pages.
  if [[ "$destination_file" == *.html ]]; then
    sed -i "s/__BASKET_MANIFEST_FILE__/${MANIFEST_FILE}/g" "$destination_file"
  fi
}

for dir_to_copy in "${COPY_DIRECTORIES[@]}"; do
  if [[ -d "$dir_to_copy" ]]; then
    cp -R "$dir_to_copy" "$OUT_DIR/"
  fi
done

for page in "${HTML_PAGES[@]}"; do
  copy_contract_file "$page"
done

for module in "${JS_MODULES[@]}"; do
  copy_contract_file "$module"
done

if ls "$PROCESSED_DATA_DIR"/*.json 1>/dev/null 2>&1; then
  cp "$PROCESSED_DATA_DIR"/*.json "$OUT_DIR/assets/processed/"
  echo "✓ Data files copied from ${PROCESSED_DATA_DIR}/ (canonical per contract)"
else
  echo "✗ No data files found in ${PROCESSED_DATA_DIR}/"
  echo "  Build contract requires processed data in ${PROCESSED_DATA_DIR}/"
  exit 1
fi

mkdir -p "$OUT_DIR/assets"
for glob in "${OPTIONAL_ASSET_GLOBS[@]}"; do
  if compgen -G "$glob" > /dev/null; then
    cp $glob "$OUT_DIR/assets/"
    echo "✓ Optional assets copied for pattern: $glob"
  else
    echo "⚠  No files found for optional pattern: $glob"
  fi
done

echo ""
echo "✓ Bundle ready: ${OUT_DIR}/"
echo "  (Built per config/build_contract.json, mode=${MODE})"
echo ""