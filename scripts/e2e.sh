#!/usr/bin/env sh

# Run headless E2E Tests with Cypress

set -e

COMPOSE_FILE="e2e/docker-compose.yml"
SPEC="${CYPRESS_SPEC:-cypress/e2e/*.cy.js}"

if [ -n "${CYPRESS_BASE_URL:-}" ]; then
	echo "Using custom Cypress base URL: ${CYPRESS_BASE_URL}"
fi

# HEADLESS CYPRESS
docker-compose -f "$COMPOSE_FILE" run --rm --build \
	-e CYPRESS_baseUrl="${CYPRESS_BASE_URL:-http://my_app:8080}" \
	-e CYPRESS_SPEC="$SPEC" \
	cypress
EXIT_CODE=$?
docker-compose -f "$COMPOSE_FILE" down
exit $EXIT_CODE
