#!/usr/bin/env bash
# build_bundle.sh — shared bundle builder for app and lab surfaces.
#
# Usage:
#   scripts/build_bundle.sh --mode app --out public
#   scripts/build_bundle.sh --mode lab --out public-lab

set -euo pipefail

MODE="app"
OUT_DIR=""
ENFORCE_HEAD_CHECK="${BASKET_ENFORCE_HEAD_CHECK:-0}"

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

# Read build config and validate required files exist
echo "→ Validating build config from config/build_config.jsonc..."
BUILD_CONFIG_FILE="config/build_config.jsonc"
if [[ ! -f "$BUILD_CONFIG_FILE" ]]; then
  echo "✗ Build config not found: $BUILD_CONFIG_FILE"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "✗ jq is required to read ${BUILD_CONFIG_FILE}"
  exit 1
fi

load_json_with_comments() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

# Strip // line comments and /* ... */ block comments for JSONC-style config files.
text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
text = re.sub(r"^\s*//.*$", "", text, flags=re.M)

obj = json.loads(text)
print(json.dumps(obj, separators=(",", ":")))
PY
}

BUILD_CONFIG_JSON="$(load_json_with_comments "$BUILD_CONFIG_FILE")"

MODE_CONFIG_JSON="$(jq -c --arg mode "$MODE" '
  def merged_mode($m):
  .modes[$m] as $cur
  | (if (($cur.inherits_from? // "") != "") then merged_mode($cur.inherits_from) else {} end) as $parent
  | {
    required_static_files: (($parent.required_static_files // {}) + ($cur.required_static_files // {})),
    path_patterns: (((($parent.path_patterns // []) + ($cur.path_patterns // [])) | unique)),
    html_pages: (((($parent.html_pages // []) + ($cur.html_pages // [])) | unique)),
    js_modules: (((($parent.js_modules // []) + ($cur.js_modules // [])) | unique)),
    copy_directories: (((($parent.copy_directories // []) + ($cur.copy_directories // [])) | unique))
  };
  {
  processed_data_dir: (.sources.processed_data_dir // "data"),
  raw_data_dir: (.sources.raw_data_dir // "assets"),
  mode: merged_mode($mode)
  }
' <<<"$BUILD_CONFIG_JSON")"

RUNTIME_CONFIG_JSON="$(jq -c '
  {
    processed_subdir: (.assets.processed_subdir // "assets/processed"),
    raw_assets_subdir: (.assets.raw_assets_subdir // "assets"),
    default_bundle_file: (.assets.default_bundle_file // "multi_drilldown_real_data.json"),
    manifest_file: (.assets.manifest_file // "games_manifest.json"),
    raw_pts_pattern: (.assets.raw_pts_pattern // "raw_pts_{season}_{game}.json"),
    elo_pattern: (.assets.elo_pattern // "elo_{season}.json"),
    style_insights_pattern: (.assets.style_insights_pattern // "style_insights_{season}.json")
  }
' <<<"$BUILD_CONFIG_JSON")"

PROCESSED_DATA_DIR="$(jq -r '.processed_data_dir' <<<"$MODE_CONFIG_JSON")"
RAW_DATA_DIR="$(jq -r '.raw_data_dir' <<<"$MODE_CONFIG_JSON")"
RUNTIME_PROCESSED_SUBDIR="$(jq -r '.processed_subdir' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_RAW_ASSETS_SUBDIR="$(jq -r '.raw_assets_subdir' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_DEFAULT_BUNDLE_FILE="$(jq -r '.default_bundle_file' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_MANIFEST_FILE="$(jq -r '.manifest_file' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_RAW_PTS_PATTERN="$(jq -r '.raw_pts_pattern' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_ELO_PATTERN="$(jq -r '.elo_pattern' <<<"$RUNTIME_CONFIG_JSON")"
RUNTIME_STYLE_INSIGHTS_PATTERN="$(jq -r '.style_insights_pattern' <<<"$RUNTIME_CONFIG_JSON")"
mapfile -t REQUIRED_STATIC_FILES < <(jq -r '.mode.required_static_files | keys[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t REQUIRED_PER_GAME_PATTERNS < <(jq -r '.mode.path_patterns[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t COPY_ASSET_GLOBS < <(jq -r --arg rawPrefix "${RAW_DATA_DIR}/" '.mode.path_patterns[]? | select(startswith($rawPrefix))' <<<"$MODE_CONFIG_JSON")
mapfile -t HTML_PAGES < <(jq -r '.mode.html_pages[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t JS_MODULES < <(jq -r '.mode.js_modules[]?' <<<"$MODE_CONFIG_JSON")
mapfile -t COPY_DIRECTORIES < <(jq -r '.mode.copy_directories[]?' <<<"$MODE_CONFIG_JSON")

declare -a PER_GAME_PATTERN_COUNTS=()

# Derive runtime manifest filename from required_static_files so the build config
# has a single declaration of this requirement.
MANIFEST_FILE="$(jq -r '
  [(.mode.required_static_files | keys[]?)
   | select(test("(^|/)games_manifest\\.json$"))
   | split("/") | last][0] // "games_manifest.json"
' <<<"$MODE_CONFIG_JSON")"
if [[ -n "$RUNTIME_MANIFEST_FILE" ]]; then
  MANIFEST_FILE="$RUNTIME_MANIFEST_FILE"
fi

for req_file in "${REQUIRED_STATIC_FILES[@]}"; do
  if [[ ! -f "$req_file" ]]; then
    echo "✗ Build config violation: required file missing: $req_file"
    exit 1
  fi
done

game_files_found=0
REQUIRE_RAW_PTS=0
REQUIRE_SCORE_TIMELINE=0
for pattern in "${REQUIRED_PER_GAME_PATTERNS[@]}"; do
  if [[ "$pattern" == *"/raw_pts_E*.json" || "$pattern" == "raw_pts_E*.json" ]]; then
    REQUIRE_RAW_PTS=1
  fi
  if [[ "$pattern" == *"/score_timeline_E*.json" || "$pattern" == "score_timeline_E*.json" ]]; then
    REQUIRE_SCORE_TIMELINE=1
  fi
  count=$(compgen -G "$pattern" | wc -l || true)
  if [[ "$count" -eq 0 ]]; then
    echo "✗ Build config violation: no files found for pattern: $pattern"
    echo "  Pipeline must generate these outputs before bundling."
    exit 1
  fi
  game_files_found=$((game_files_found + count))
  PER_GAME_PATTERN_COUNTS+=("${count}")
done

MANIFEST_PATH="${PROCESSED_DATA_DIR}/${MANIFEST_FILE}"
manifest_entries=0
missing_entries=0
missing_raw_pts=0
missing_score_timeline=0
head_checked_count=0
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
    echo "✗ Build config violation: manifest references ${missing_entries} missing per-game files"
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
      echo "✗ Build config violation: manifest references ${missing_raw_pts} games without raw_pts timeline JSON"
      if [[ -n "$missing_raw_pts_sample" ]]; then
        echo "  Missing raw_pts sample: ${missing_raw_pts_sample}"
      fi
      echo "  Cone chart requires raw_pts_{season}_{game}.json for each game in manifest."
      exit 1
    fi
    echo "✓ raw_pts coverage validated (0 missing files)"
  fi

  if [[ "$REQUIRE_SCORE_TIMELINE" -eq 1 ]]; then
    echo "→ Validating score_timeline coverage from manifest..."
    score_timeline_report="$(python3 - "$MANIFEST_PATH" "$PROCESSED_DATA_DIR" <<'PY'
import json
import os
import sys

manifest_path = sys.argv[1]
processed_data_dir = sys.argv[2]

with open(manifest_path, encoding="utf-8") as f:
    manifest = json.load(f)

missing = []
for row in manifest:
    season = row.get("seasoncode")
    gamecode = row.get("gamecode")
    if not season or gamecode is None:
        continue
    fname = f"score_timeline_{season}_{gamecode}.json"
    fpath = os.path.join(processed_data_dir, fname)
    if not os.path.isfile(fpath):
        missing.append(fname)

print(f"missing_score_timeline={len(missing)}")
if missing:
    print("missing_score_timeline_sample=" + ", ".join(missing[:10]))
PY
)"

    missing_score_timeline="$(echo "$score_timeline_report" | awk -F= '/^missing_score_timeline=/{print $2}')"
    missing_score_timeline_sample="$(echo "$score_timeline_report" | awk -F= '/^missing_score_timeline_sample=/{print $2}')"

    if [[ "$missing_score_timeline" != "0" ]]; then
      echo "✗ Build config violation: manifest references ${missing_score_timeline} games without score_timeline JSON"
      if [[ -n "$missing_score_timeline_sample" ]]; then
        echo "  Missing score_timeline sample: ${missing_score_timeline_sample}"
      fi
      echo "  Score-diff/score-d52 pages require score_timeline_{season}_{game}.json for each game in manifest."
      exit 1
    fi
    echo "✓ score_timeline coverage validated (0 missing files)"
  fi
fi

if [[ "$ENFORCE_HEAD_CHECK" == "1" ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "→ Validating config-required files are committed in HEAD..."
  missing_from_head_count=0
  missing_from_head_sample=()

  if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "✗ Build config violation: no HEAD commit found"
    echo "  Preflight cannot verify required files against committed history in an unborn repository."
    exit 1
  fi

  check_path_in_head() {
    local path="$1"
    if [[ -z "$path" ]]; then
      return
    fi
    head_checked_count=$((head_checked_count + 1))
    if ! git cat-file -e "HEAD:$path" >/dev/null 2>&1; then
      missing_from_head_count=$((missing_from_head_count + 1))
      if [[ "${#missing_from_head_sample[@]}" -lt 10 ]]; then
        missing_from_head_sample+=("$path")
      fi
    fi
  }

  for req_file in "${REQUIRED_STATIC_FILES[@]}"; do
    check_path_in_head "$req_file"
  done

  if [[ -f "$MANIFEST_PATH" ]]; then
    check_path_in_head "$MANIFEST_PATH"
    manifest_required_paths="$(python3 - "$MANIFEST_PATH" "$PROCESSED_DATA_DIR" "$RAW_DATA_DIR" "$REQUIRE_RAW_PTS" "$REQUIRE_SCORE_TIMELINE" <<'PY'
import json
import os
import sys

manifest_path = sys.argv[1]
processed_dir = sys.argv[2]
raw_dir = sys.argv[3]
require_raw_pts = sys.argv[4] == "1"
require_score_timeline = sys.argv[5] == "1"

with open(manifest_path, encoding="utf-8") as f:
    manifest = json.load(f)

paths = []
for row in manifest:
    fname = row.get("file")
    if fname:
        paths.append(os.path.join(processed_dir, fname))

    if require_raw_pts:
        season = row.get("seasoncode")
        gamecode = row.get("gamecode")
        if season and gamecode is not None:
            paths.append(os.path.join(raw_dir, f"raw_pts_{season}_{gamecode}.json"))

    if require_score_timeline:
        season = row.get("seasoncode")
        gamecode = row.get("gamecode")
        if season and gamecode is not None:
            paths.append(os.path.join(processed_dir, f"score_timeline_{season}_{gamecode}.json"))

for p in sorted(set(paths)):
    print(p)
PY
)"

    while IFS= read -r path; do
      [[ -z "$path" ]] && continue
      check_path_in_head "$path"
    done <<< "$manifest_required_paths"
  fi

  if [[ "$missing_from_head_count" -ne 0 ]]; then
    echo "✗ Build config violation: ${missing_from_head_count} required files are not present in HEAD"
    if [[ "${#missing_from_head_sample[@]}" -gt 0 ]]; then
      echo "  Missing-from-HEAD sample: ${missing_from_head_sample[*]}"
    fi
    echo "  Staged-only files do not count; the required files must already be committed."
    echo "  Commit and push the missing files before bundling/deploying."
    exit 1
  fi

  echo "✓ HEAD commit contains all config-required files"
fi

echo ""
echo "Validation Check Summary"
printf "%-42s | %-26s | %-10s | %-8s\n" "Target" "Checks" "Count" "Result"
printf "%-42s-+-%-26s-+-%-10s-+-%-8s\n" "------------------------------------------" "--------------------------" "----------" "--------"
printf "%-42s | %-26s | %-10s | %-8s\n" "config/build_config.jsonc" "presence, parse" "1" "OK"
printf "%-42s | %-26s | %-10s | %-8s\n" "required_static_files" "presence, HEAD" "${#REQUIRED_STATIC_FILES[@]}" "OK"
if [[ -f "$MANIFEST_PATH" ]]; then
  printf "%-42s | %-26s | %-10s | %-8s\n" "${MANIFEST_PATH}" "presence, coverage, HEAD" "1" "OK"
  printf "%-42s | %-26s | %-10s | %-8s\n" "manifest listed game files" "presence, HEAD" "${manifest_entries}" "OK"
fi

for i in "${!REQUIRED_PER_GAME_PATTERNS[@]}"; do
  pattern="${REQUIRED_PER_GAME_PATTERNS[$i]}"
  pcount="${PER_GAME_PATTERN_COUNTS[$i]}"
  pchecks="glob_presence"
  if [[ "$pattern" == *"multi_drilldown_real_data_E*.json"* ]]; then
    pchecks="glob_presence, manifest, HEAD"
  elif [[ "$pattern" == *"raw_pts_E*.json"* ]]; then
    pchecks="glob_presence, manifest, HEAD (cone+diff+d52+v2)"
  elif [[ "$pattern" == *"score_timeline_E*.json"* ]]; then
    pchecks="glob_presence, manifest, HEAD (diff+d52 precomputed)"
  fi
  printf "%-42s | %-26s | %-10s | %-8s\n" "$pattern" "$pchecks" "$pcount" "OK"
done

if [[ -n "${head_checked_count}" && "$head_checked_count" -gt 0 ]]; then
  printf "%-42s | %-26s | %-10s | %-8s\n" "HEAD object checks (total)" "HEAD presence" "$head_checked_count" "OK"
fi

echo "✓ Build config validated (${game_files_found} files found across required per-game patterns)"

echo "→ Building ${OUT_DIR}/ bundle (mode=${MODE})..."
rm -rf "$OUT_DIR"

if [[ "$MODE" == "app" ]]; then
  mkdir -p "$OUT_DIR/assets/processed" "$OUT_DIR/src" "$OUT_DIR/lab"
else
  mkdir -p "$OUT_DIR/assets/processed" "$OUT_DIR/prod" "$OUT_DIR/src" "$OUT_DIR/lab"
fi

copy_config_file() {
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

  # Inject runtime asset settings from config into HTML pages.
  if [[ "$destination_file" == *.html || "$destination_file" == *.js ]]; then
    sed -i "s/__BASKET_MANIFEST_FILE__/${MANIFEST_FILE}/g" "$destination_file"
    sed -i "s#__BASKET_PROCESSED_SUBDIR__#${RUNTIME_PROCESSED_SUBDIR}#g" "$destination_file"
    sed -i "s#__BASKET_RAW_ASSETS_SUBDIR__#${RUNTIME_RAW_ASSETS_SUBDIR}#g" "$destination_file"
    sed -i "s/__BASKET_DEFAULT_BUNDLE_FILE__/${RUNTIME_DEFAULT_BUNDLE_FILE}/g" "$destination_file"
    sed -i "s/__BASKET_RAW_PTS_PATTERN__/${RUNTIME_RAW_PTS_PATTERN}/g" "$destination_file"
    sed -i "s/__BASKET_ELO_PATTERN__/${RUNTIME_ELO_PATTERN}/g" "$destination_file"
    sed -i "s/__BASKET_STYLE_INSIGHTS_PATTERN__/${RUNTIME_STYLE_INSIGHTS_PATTERN}/g" "$destination_file"
  fi
}

for dir_to_copy in "${COPY_DIRECTORIES[@]}"; do
  if [[ -d "$dir_to_copy" ]]; then
    cp -R "$dir_to_copy" "$OUT_DIR/"
  fi
done

for page in "${HTML_PAGES[@]}"; do
  copy_config_file "$page"
done

for module in "${JS_MODULES[@]}"; do
  copy_config_file "$module"
done

if ls "$PROCESSED_DATA_DIR"/*.json 1>/dev/null 2>&1; then
  cp "$PROCESSED_DATA_DIR"/*.json "$OUT_DIR/assets/processed/"
  echo "✓ Data files copied from ${PROCESSED_DATA_DIR}/ (canonical per build config)"
else
  echo "✗ No data files found in ${PROCESSED_DATA_DIR}/"
  echo "  Build config requires processed data in ${PROCESSED_DATA_DIR}/"
  exit 1
fi

mkdir -p "$OUT_DIR/assets"
for glob in "${COPY_ASSET_GLOBS[@]}"; do
  if compgen -G "$glob" > /dev/null; then
    cp $glob "$OUT_DIR/assets/"
    echo "✓ Assets copied for pattern: $glob"
  else
    echo "⚠  No files found for configured asset pattern: $glob"
  fi
done

echo ""
echo "✓ Bundle ready: ${OUT_DIR}/"
echo "  (Built per config/build_config.jsonc, mode=${MODE})"
echo ""