#!/usr/bin/env bash
# serve.sh — build public/ (same structure as CI) and serve locally.
#
# Usage:
#   ./serve.sh          # build and serve on :8080
#   PORT=9000 ./serve.sh
#
# Generate data first if you haven't already:
#   docker compose run --rm demo

set -euo pipefail

PORT="${PORT:-8080}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

scripts/build_bundle.sh --mode app --out public

echo "→ Serving public/ on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/index.html"
echo "   Open: http://localhost:${PORT}/elo.html?season=2025-2026"
echo "   Open: http://localhost:${PORT}/score-diff.html"
echo "   Open: http://localhost:${PORT}/score-d52.html"
echo "   Open: http://localhost:${PORT}/score-diff-v2.html"
echo "   Open: http://localhost:${PORT}/score-d52-v2.html"
echo "   Open: http://localhost:${PORT}/style-insights.html"
python3 -m http.server "$PORT" --directory public
