# Local commands mirror CI exactly, so a green `make ci` means a green pipeline.
.DEFAULT_GOAL := help
.PHONY: help setup lint format types test cov ci kb run clean

help:  ## Show available commands
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## Install the pinned Python and all dependencies
	uv python install
	uv sync --all-extras --group dev
	@test -f .env || (cp .env.example .env && echo "Created .env — add your API key")

lint:  ## Lint + security rules (ruff, includes bandit's checks)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix and format
	uv run ruff check --fix .
	uv run ruff format .

types:  ## Strict type checking
	uv run mypy

test:  ## Run the test suite
	uv run pytest

cov:  ## Run tests with a coverage report
	uv run pytest --cov --cov-report=term-missing

ci: lint types cov  ## Everything CI runs, locally

kb:  ## Regenerate the knowledge base from the live site (ARGS=--offline to use cache)
	uv run --extra kb python knowledge-base/build_kb.py $(ARGS)

kb-check:  ## Fail if the committed knowledge base is stale (runs in CI)
	uv run --extra kb python knowledge-base/build_kb.py --check

run:  ## Start the API with auto-reload
	uv run uvicorn app.main:app --reload --port 8000

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml requirements.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
