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
	uv run --all-extras ruff check .
	uv run --all-extras ruff format --check .

format:  ## Auto-fix and format
	uv run --all-extras ruff check --fix .
	uv run --all-extras ruff format .

types:  ## Strict type checking
	uv run --all-extras mypy

test:  ## Run the test suite
	uv run --all-extras pytest

cov:  ## Run tests with a coverage report
	uv run --all-extras pytest --cov --cov-report=term-missing

cov-guardrails:  ## Guardrails carry a higher bar than the rest of the codebase
	uv run --all-extras pytest --cov=backend/app/domain/guardrails --cov-fail-under=95 -q

ci: lint types cov cov-guardrails  ## Everything CI runs, locally

kb:  ## Regenerate the knowledge base from the live site (ARGS=--offline to use cache)
	uv run --extra kb python knowledge-base/build_kb.py $(ARGS)

kb-check:  ## Fail if the committed knowledge base is stale (runs in CI)
	uv run --extra kb python knowledge-base/build_kb.py --check

run:  ## Start the API with auto-reload
	uv run --all-extras uvicorn app.main:create_app --factory --reload --port 8000

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml requirements.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
