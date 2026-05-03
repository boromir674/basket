#!/usr/bin/env sh

# Run headless E2E Tests with Cypress

set -e

# HEADLESS CYPRESS
docker-compose -f e2e/docker-compose.yml run --rm --build cypress
EXIT_CODE=$?
docker-compose -f e2e/docker-compose.yml down
exit $EXIT_CODE
