.PHONY: help sync-season normalize-season elo report prepare-season test

help:
	@echo "Targets:"
	@echo "  make sync-season SEASON=E2025 START=1 END=200"
	@echo "  make normalize-season SEASON=E2025"
	@echo "  make elo SEASON=E2025"
	@echo "  make report SEASON=E2025"
	@echo "  make prepare-season SEASON=E2025 START=1 END=200"
	@echo "  make test"

SEASON ?= E2025
START ?= 1
END ?= 200
DATA_DIR ?= /app/data
CONCURRENCY ?= 1
PRESSURE ?= 1.0
RETRY_PASS ?= 1
LOG_LEVEL ?= INFO

sync-season:
	docker-compose run --rm ops sync_season --seasoncode $(SEASON) --start-gamecode $(START) --end-gamecode $(END) --output-dir $(DATA_DIR) --concurrency $(CONCURRENCY) --pressure $(PRESSURE) --log-level $(LOG_LEVEL) $(if $(filter $(RETRY_PASS),1 true TRUE yes YES),--retry-pass,)

normalize-season:
	docker-compose run --rm ops normalize_season_data --seasoncode $(SEASON) --data-dir $(DATA_DIR)

elo:
	docker-compose run --rm ops compute_elo --seasoncode $(SEASON) --output-dir $(DATA_DIR)

report:
	docker-compose run --rm ops report_season --seasoncode $(SEASON) --data-dir $(DATA_DIR)

prepare-season:
	docker-compose run --rm ops prepare_season --seasoncode $(SEASON) --start-gamecode $(START) --end-gamecode $(END) --data-dir $(DATA_DIR)

test:
	docker-compose run --rm --build tests
