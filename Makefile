.PHONY: help dev lab preflight preflight-app preflight-lab preflight-clean install-hooks sync-season sync-seasons normalize-season normalize-all-seasons backfill-gamedates redo-season elo elo-multi elo-auto check-dates manifest-sanity report prepare-season test

help:
	@echo "Targets:"
	@echo "  make sync-season-full SEASON=E2025"
	@echo "  make sync-season SEASON=E2025"
	@echo "  make sync-seasons SEASONS='E2022 E2023 E2024'"
	@echo "  make normalize-season SEASON=E2025 NORMALIZE_WORKERS=8"
	@echo "  make normalize-all-seasons NORMALIZE_WORKERS=8"
	@echo "  make check-dates [SEASON=E2025] [DATA_DIR=/app/data]"
	@echo "  make manifest-sanity [DATA_DIR=/app/data]"
	@echo "  make backfill-gamedates SEASON=E2025 RAW_DIR=/app/assets"
	@echo "  make elo SEASON=E2025"
	@echo "  make elo-multi SEASONS='E2022,E2023,E2024'"
	@echo "  make elo-auto"
	@echo "  make dev [PORT=8080]"
	@echo "  make lab [PORT=8081]"
	@echo "  make preflight"
	@echo "  make preflight-app"
	@echo "  make preflight-lab"
	@echo "  make preflight-clean"
	@echo "  make install-hooks"
	@echo "  make report SEASON=E2025"
	@echo "  make prepare-season SEASON=E2025 START=1 END=200"
	@echo "  make test"

SEASON ?= E2025
DATA_DIR ?= /app/data
CONCURRENCY ?= 8
GAP_LIMIT ?= 10
MAX_GAMECODE ?= 999
NORMALIZE_WORKERS ?= 8
PRESSURE ?= 1.0
RETRY_PASS ?= 1
LOG_LEVEL ?= INFO
RAW_DIR ?= /app/assets
SEASONS ?= E2017 E2018 E2019 E2020 E2021 E2022 E2023 E2024
SEASONS_CSV ?= E2017,E2018,E2019,E2020,E2021,E2022,E2023,E2024
PORT ?= 8080

dev:
	PORT=$(PORT) ./serve.sh

lab:
	PORT=$(PORT) ./serve-lab.sh

preflight:
	./scripts/preflight.sh --mode all

preflight-app:
	./scripts/preflight.sh --mode app

preflight-lab:
	./scripts/preflight.sh --mode lab

preflight-clean:
	./scripts/preflight.sh --mode app --require-clean

install-hooks:
	./scripts/install_git_hooks.sh

redo-season:
	docker-compose run --rm --build ops redo_season --seasoncode $(SEASON) --data-dir $(DATA_DIR) --raw-dir $(RAW_DIR) --concurrency $(CONCURRENCY) --gap-limit $(GAP_LIMIT) --max-gamecode $(MAX_GAMECODE)

sync-season-full:
	docker-compose run --rm --build ops sync_season_full --seasoncode $(SEASON) --output-dir $(DATA_DIR)

sync-season:
	docker-compose run --rm --build ops sync_season --seasoncode $(SEASON) --output-dir $(DATA_DIR) --concurrency $(CONCURRENCY) --pressure $(PRESSURE) --log-level $(LOG_LEVEL) $(if $(filter $(RETRY_PASS),1 true TRUE yes YES),--retry-pass,)

sync-seasons:
	@set -e; \
	for s in $(SEASONS); do \
	  echo "=== sync $$s (scan mode: tail stop at 5 misses) ==="; \
	  $(MAKE) sync-season SEASON=$$s DATA_DIR=$(DATA_DIR) CONCURRENCY=$(CONCURRENCY) PRESSURE=$(PRESSURE) RETRY_PASS=$(RETRY_PASS) LOG_LEVEL=$(LOG_LEVEL); \
	done

normalize-season:
	docker-compose run --rm --build ops normalize_season_data --seasoncode $(SEASON) --data-dir $(DATA_DIR) --workers $(NORMALIZE_WORKERS)

normalize-all-seasons:
	docker-compose run --rm --build ops normalize_all_seasons --data-dir $(DATA_DIR) --workers $(NORMALIZE_WORKERS)

check-dates:
	docker-compose run --rm ops check_dates --data-dir $(DATA_DIR) $(if $(SEASON),--seasoncode $(SEASON),)

manifest-sanity:
	docker-compose run --build --rm --entrypoint python ops /app/scripts/check_manifest_sanity.py --data-dir $(DATA_DIR)

backfill-gamedates:
	docker-compose run --rm ops backfill_gamedates --seasoncode $(SEASON) --data-dir $(DATA_DIR) --raw-dir $(RAW_DIR)

elo:
	docker-compose run --rm ops compute_elo --seasoncode $(SEASON) --output-dir $(DATA_DIR)

elo-multi:
	docker-compose run --rm ops compute_elo --seasoncodes $(SEASONS_CSV) --output-dir $(DATA_DIR) --output-name elo_multiseason.json

elo-auto:
	docker-compose run --rm ops compute_elo --auto --output-dir $(DATA_DIR) --output-name elo_multiseason.json

report:
	@set -e; \
	for s in $(SEASONS) $(SEASON); do \
	  docker-compose run --rm ops report_season --seasoncode $$s --data-dir $(DATA_DIR); \
	done

prepare-season:
	docker-compose run --rm ops prepare_season --seasoncode $(SEASON) --start-gamecode $(START) --end-gamecode $(END) --data-dir $(DATA_DIR)

test:
	docker-compose run --rm --build tests $(ARGS)


# headless cypress tests
e2e:
	./scripts/e2e.sh


# run Cypress with GUI (for debugging)
e2e-gui:
	./e2e/run-cypress-gui.sh
