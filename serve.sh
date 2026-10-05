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

# in case running on older hosts, python distirubtion installed might ship older version of http.server, so we do a little check here to, just make it
# a bit more backwards compatible.

# older http.server versions do not support --directory public, so we must
# find workaraound, with a conditional

if ! python3 -m http.server --help | grep -q -- '--directory'; then
  echo "[INFO] Your Python http.server does not support --directory. Using workaround."
  cd public
  python3 -m http.server "$PORT"

else
  python3 -m http.server "$PORT" --directory public
fi
