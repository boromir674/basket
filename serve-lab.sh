#!/usr/bin/env bash
# serve-lab.sh — build a lab-first bundle and serve it locally.
#
# Usage:
#   ./serve-lab.sh
#   PORT=9001 ./serve-lab.sh

set -euo pipefail

PORT="${PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

scripts/build_bundle.sh --mode lab --out public-lab

echo "→ Serving public-lab/ on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/lab/index.html"
echo "   Open: http://localhost:${PORT}/lab/shot-style-map.html"
echo "   Open: http://localhost:${PORT}/lab/style-consistency-lab.html"
echo "   Open: http://localhost:${PORT}/prod/style-insights.html"
echo "   Open: http://localhost:${PORT}/prod/score-d52-v2.html"
python3 -m http.server "$PORT" --directory public-lab