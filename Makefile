.PHONY: install lint format test up down logs smoke clean

install:  ## Install development dependencies
	pip install -r requirements-dev.txt

lint:     ## Lint and format check
	ruff check . && ruff format --check .

format:   ## Auto-fix and format the code
	ruff check --fix . && ruff format .

test:     ## Run tests with coverage
	pytest --cov=api

up:       ## Build and start the whole stack
	docker compose up -d --build

down:     ## Stop the stack (data is kept)
	docker compose down

logs:     ## Follow the logs of all services
	docker compose logs -f

smoke:    ## Smoke test the running stack
	./scripts/smoke_test.sh

clean:    ## Remove the stack and its volumes, clear caches
	docker compose down -v && rm -rf .pytest_cache .ruff_cache .coverage
