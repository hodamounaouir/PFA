.PHONY: setup test lint check

setup:
	uv sync
	@test -f .env || cp .env.example .env
	@echo "✅ Environnement prêt. Renseigne les clés dans .env"

test:
	uv run pytest

lint:
	uv run ruff check .

check: lint test
