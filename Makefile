.PHONY: setup test lint check dbt-debug dbt-run dbt-test dbt-build

setup:
	uv sync
	@test -f .env || cp .env.example .env
	@echo "✅ Environnement prêt. Renseigne les clés dans .env"

test:
	uv run pytest

lint:
	uv run ruff check .

check: lint test

# --- dbt (phase 2.2) : charge le .env puis lance dbt depuis dbt/ ---
# profiles.yml est dans dbt/ → --profiles-dir .
dbt-debug:
	set -a; . ./.env; set +a; cd dbt && uv run dbt debug --profiles-dir .

dbt-run:
	set -a; . ./.env; set +a; cd dbt && uv run dbt run --profiles-dir .

dbt-test:
	set -a; . ./.env; set +a; cd dbt && uv run dbt test --profiles-dir .

dbt-build:
	set -a; . ./.env; set +a; cd dbt && uv run dbt build --profiles-dir .
