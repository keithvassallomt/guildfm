.PHONY: install dev build serve backup update test lint format migration

install:  ## Install Python and front end dependencies
	uv sync
	cd web && npm install

dev:  ## Run the API and front end with live reload (phones: http://<this machine>:5173)
	./scripts/dev.sh

build:  ## Build the front end into web/dist
	cd web && npm run build

serve: build  ## Build, then run GuildFM as it runs in production (http://<this machine>:8000)
	uv run guildfm

backup:  ## Make a backup now: the database and uploaded media, as a zip in data/backups
	uv run guildfm backup

update:  ## On the office machine: pull, rebuild, back up and restart the service
	./scripts/update.sh

test:  ## Run the backend tests
	uv run pytest

lint:  ## Check Python style and front end types
	uv run ruff check .
	uv run ruff format --check .
	cd web && npm run typecheck

format:  ## Fix Python formatting and lint issues
	uv run ruff format .
	uv run ruff check --fix .

migration:  ## Create a migration from model changes: make migration m="add users"
	uv run alembic revision --autogenerate -m "$(m)"
