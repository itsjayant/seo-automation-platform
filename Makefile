# SEO Automation Platform - Development Makefile  
.DEFAULT_GOAL := help
.PHONY: help setup start stop restart logs health migrate validate test clean install-dev lint format check-types

# Variables
PYTHON := python
PIP := pip
PYTEST := pytest
COVERAGE := coverage
BLACK := black
RUFF := ruff
MYPY := mypy
COMPOSE_CMD := $(shell if command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)

# Colors for output
BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)SEO Automation Platform - Developer Commands$(NC)"
	@echo ""
	@echo "$(YELLOW)Infrastructure:$(NC)"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {if ($$0 ~ /Infrastructure/) print "$(GREEN)%-20s$(NC) %s", $$1, $$2}' $(MAKEFILE_LIST) | head -10
	@echo ""
	@echo "$(YELLOW)Validation & Testing:$(NC)"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {if ($$0 ~ /Validation|test/) print "$(GREEN)%-20s$(NC) %s", $$1, $$2}' $(MAKEFILE_LIST) | head -10  
	@echo ""
	@echo "$(YELLOW)Development:$(NC)"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {if ($$0 ~ /Development|format|lint/) print "$(GREEN)%-20s$(NC) %s", $$1, $$2}' $(MAKEFILE_LIST) | head -10
	@echo ""
	@echo "$(BLUE)For full command list: make help-all$(NC)"

help-all: ## Show all available commands
	@echo "$(BLUE)SEO Automation Platform - All Commands$(NC)"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "$(GREEN)%-20s$(NC) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# =============================================================================
# Infrastructure Commands
# =============================================================================

setup: ## Infrastructure: Fresh environment setup
	@echo "$(BLUE)Setting up fresh SEO Platform environment...$(NC)"
	@echo "$(YELLOW)1. Installing dependencies...$(NC)"
	$(MAKE) install-dev
	@echo "$(YELLOW)2. Starting Docker services...$(NC)"
	$(MAKE) start
	@echo "$(YELLOW)3. Waiting for services to be ready...$(NC)"
	@sleep 10
	@echo "$(YELLOW)4. Running database migrations...$(NC)"
	$(MAKE) migrate
	@echo "$(YELLOW)5. Validating setup...$(NC)"
	$(MAKE) health
	@echo "$(GREEN)✅ Environment setup complete!$(NC)"

start: ## Infrastructure: Start Docker Compose services
	@echo "$(BLUE)Starting Docker services...$(NC)"
	$(COMPOSE_CMD) up -d
	@echo "$(GREEN)Services started. Use 'make logs' to view output.$(NC)"

stop: ## Infrastructure: Stop Docker Compose services
	@echo "$(BLUE)Stopping Docker services...$(NC)"
	$(COMPOSE_CMD) down
	@echo "$(GREEN)Services stopped.$(NC)"

restart: ## Infrastructure: Restart Docker Compose services
	@echo "$(BLUE)Restarting Docker services...$(NC)"
	$(COMPOSE_CMD) restart
	@echo "$(GREEN)Services restarted.$(NC)"

logs: ## Infrastructure: View Docker Compose logs
	@echo "$(BLUE)Showing service logs (press Ctrl+C to exit)...$(NC)"
	$(COMPOSE_CMD) logs -f

logs-postgres: ## Infrastructure: View PostgreSQL logs only
	$(COMPOSE_CMD) logs -f postgres

logs-redis: ## Infrastructure: View Redis logs only  
	$(COMPOSE_CMD) logs -f redis

logs-nats: ## Infrastructure: View NATS logs only
	$(COMPOSE_CMD) logs -f nats

health: ## Infrastructure: Run health checks on all services
	@echo "$(BLUE)Running infrastructure health checks...$(NC)"
	$(PYTHON) scripts/health-check.py --verbose

migrate: ## Infrastructure: Run database migrations
	@echo "$(BLUE)Running database migrations...$(NC)"
	alembic upgrade head
	@echo "$(GREEN)Migrations completed.$(NC)"

migrate-rollback: ## Infrastructure: Rollback database migrations  
	@echo "$(BLUE)Rolling back database migrations...$(NC)"
	@echo "$(RED)WARNING: This will rollback to base schema!$(NC)"
	@read -p "Are you sure? (y/N): " confirm && [ "$$confirm" = "y" ]
	alembic downgrade base
	@echo "$(YELLOW)Database rolled back to base schema.$(NC)"

# =============================================================================
# Phase 1 Validation Commands
# =============================================================================

validate: ## Validation: Run Phase 1 comprehensive validation
	@echo "$(BLUE)Running Phase 1 comprehensive validation...$(NC)"
	$(PYTHON) scripts/validate-phase1.py

validate-json: ## Validation: Run Phase 1 validation with JSON output only
	@echo "$(BLUE)Running Phase 1 validation (JSON output)...$(NC)"
	$(PYTHON) scripts/validate-phase1.py --json-only

validate-docker-skip: ## Validation: Run Phase 1 validation skipping Docker checks
	@echo "$(BLUE)Running Phase 1 validation (skip Docker)...$(NC)"
	$(PYTHON) scripts/validate-phase1.py --skip-docker

validate-extended: ## Validation: Run extended Phase 1 validation with longer timeout
	@echo "$(BLUE)Running extended Phase 1 validation...$(NC)"
	$(PYTHON) scripts/validate-phase1.py --timeout 600

# =============================================================================
# Test Commands
# =============================================================================

install-dev: ## Development: Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

clean: ## Development: Clean test artifacts and cache files
	@echo "$(BLUE)Cleaning test artifacts...$(NC)"
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -f coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage.*" -delete

# Core Test Commands
test: ## Testing: Run all tests
	@echo "$(BLUE)Running all tests...$(NC)"
	$(PYTEST) tests/ -v

test-unit: ## Testing: Run unit tests only (fast)
	@echo "$(BLUE)Running unit tests...$(NC)"
	$(PYTEST) tests/unit/ -m "unit" -v

test-integration: ## Testing: Run integration tests (requires services)
	@echo "$(BLUE)Running integration tests...$(NC)"
	@echo "$(YELLOW)Note: Requires PostgreSQL, Redis, and NATS services running$(NC)"
	$(PYTEST) tests/integrations/ -m "integration" -v

test-e2e: ## Testing: Run end-to-end tests (full system)
	@echo "$(BLUE)Running end-to-end tests...$(NC)"
	@echo "$(YELLOW)Note: Requires all services running$(NC)"
	$(PYTEST) tests/ -m "e2e" -v

test-agents: ## Testing: Run agent workflow tests
	@echo "$(BLUE)Running agent tests...$(NC)"
	$(PYTEST) tests/ -m "agents" -v

test-queue: ## Testing: Run task queue tests
	@echo "$(BLUE)Running task queue tests...$(NC)"
	$(PYTEST) tests/queue/ -m "queue" -v

test-notifications: ## Testing: Run notification system tests  
	@echo "$(BLUE)Running notification tests...$(NC)"
	$(PYTEST) tests/notifications/ -m "notifications" -v

# API Integration Tests
test-gsc: ## Testing: Run Google Search Console tests
	@echo "$(BLUE)Running GSC integration tests...$(NC)"
	$(PYTEST) tests/integrations/test_gsc.py -m "gsc" -v

test-ga4: ## Testing: Run Google Analytics 4 tests
	@echo "$(BLUE)Running GA4 integration tests...$(NC)"
	$(PYTEST) tests/integrations/test_ga4.py -m "ga4" -v

test-serpapi: ## Testing: Run SerpAPI tests
	@echo "$(BLUE)Running SerpAPI integration tests...$(NC)"
	$(PYTEST) tests/integrations/test_serp.py -m "serpapi" -v

# Coverage Commands
test-coverage: ## Testing: Run tests with coverage reporting
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	$(PYTEST) tests/ --cov=. --cov-report=term-missing --cov-report=xml --cov-fail-under=80 -v

test-coverage-html: ## Testing: Run tests with HTML coverage report
	@echo "$(BLUE)Running tests with HTML coverage report...$(NC)"
	$(PYTEST) tests/ --cov=. --cov-report=html --cov-report=term-missing --cov-fail-under=80 -v
	@echo "$(GREEN)Coverage report generated: htmlcov/index.html$(NC)"

coverage-report: ## Testing: Show coverage report (run after test-coverage)
	@echo "$(BLUE)Showing coverage report...$(NC)"
	$(COVERAGE) report --show-missing

# Parallel Test Execution
test-parallel: ## Testing: Run tests in parallel (faster for large test suites)
	@echo "$(BLUE)Running tests in parallel...$(NC)"
	$(PYTEST) tests/ -n auto -v

test-unit-parallel: ## Testing: Run unit tests in parallel
	@echo "$(BLUE)Running unit tests in parallel...$(NC)"
	$(PYTEST) tests/unit/ -m "unit" -n auto -v

# Test Categories by Speed
test-fast: ## Testing: Run only fast tests (< 1 second each)
	@echo "$(BLUE)Running fast tests...$(NC)"
	$(PYTEST) tests/ -m "not slow" -v

test-slow: ## Testing: Run only slow tests
	@echo "$(BLUE)Running slow tests...$(NC)"
	$(PYTEST) tests/ -m "slow" -v

# Database Tests
test-db: ## Testing: Run database-related tests
	@echo "$(BLUE)Running database tests...$(NC)"
	$(PYTEST) tests/ -m "database" -v

test-models: ## Testing: Run database model tests
	@echo "$(BLUE)Running model tests...$(NC)"
	$(PYTEST) tests/unit/test_models.py -v

# Service-specific Tests
test-redis: ## Testing: Run Redis-related tests
	@echo "$(BLUE)Running Redis tests...$(NC)"
	$(PYTEST) tests/ -m "redis" -v

test-nats: ## Testing: Run NATS-related tests
	@echo "$(BLUE)Running NATS tests...$(NC)" 
	$(PYTEST) tests/ -m "nats" -v

# Error Handling Tests
test-rate-limit: ## Testing: Run rate limiting tests
	@echo "$(BLUE)Running rate limiting tests...$(NC)"
	$(PYTEST) tests/ -m "rate_limit" -v

test-retry: ## Testing: Run retry mechanism tests
	@echo "$(BLUE)Running retry tests...$(NC)"
	$(PYTEST) tests/ -m "retry" -v

test-circuit-breaker: ## Testing: Run circuit breaker tests
	@echo "$(BLUE)Running circuit breaker tests...$(NC)"
	$(PYTEST) tests/ -m "circuit_breaker" -v

# =============================================================================
# Development & Code Quality Commands  
# =============================================================================

lint: ## Development: Run code linting with Ruff
	@echo "$(BLUE)Running linter...$(NC)"
	$(RUFF) check .

format: ## Development: Format code with Black
	@echo "$(BLUE)Formatting code...$(NC)"
	$(BLACK) .

check-types: ## Development: Run type checking with mypy
	@echo "$(BLUE)Running type checking...$(NC)"
	$(MYPY) . --ignore-missing-imports

# Combined Quality Checks
check: lint check-types ## Development: Run all code quality checks
	@echo "$(GREEN)All quality checks completed$(NC)"

format-check: ## Development: Check if code formatting is correct
	@echo "$(BLUE)Checking code formatting...$(NC)"
	$(BLACK) --check .

# Test Data Management
test-fixtures: ## Development: Validate test fixture data
	@echo "$(BLUE)Validating test fixtures...$(NC)"
	$(PYTHON) -c "import json; [json.load(open(f)) for f in ['tests/fixtures/gsc_responses.json', 'tests/fixtures/ga4_responses.json', 'tests/fixtures/serp_responses.json']]"
	@echo "$(GREEN)All test fixtures are valid JSON$(NC)"

# =============================================================================
# CI/CD & Workflow Commands
# =============================================================================

ci-test: clean test-coverage lint check-types ## CI/CD: Run full CI/CD test suite
	@echo "$(GREEN)CI/CD test suite completed$(NC)"

ci-test-fast: clean test-unit lint format-check ## CI/CD: Run fast CI/CD checks  
	@echo "$(GREEN)Fast CI/CD checks completed$(NC)"

# Development Workflow Commands
dev-test: test-unit test-fixtures ## Development: Quick development test cycle
	@echo "$(GREEN)Development test cycle completed$(NC)"

pre-commit: format lint check-types test-unit ## Development: Pre-commit checks
	@echo "$(GREEN)Pre-commit checks completed$(NC)"

# Debug and Troubleshooting
test-debug: ## Testing: Run tests with detailed debug output
	@echo "$(BLUE)Running tests with debug output...$(NC)"
	$(PYTEST) tests/ -v -s --tb=long --showlocals

test-failed: ## Testing: Re-run only failed tests from last run
	@echo "$(BLUE)Re-running failed tests...$(NC)"
	$(PYTEST) --lf -v

test-pdb: ## Testing: Run tests with PDB debugging on failure
	@echo "$(BLUE)Running tests with PDB debugging...$(NC)"
	$(PYTEST) tests/ --pdb -v

# =============================================================================
# Complete Workflow Commands  
# =============================================================================

full-setup: ## Workflow: Complete setup + validation (for new environments)
	@echo "$(BLUE)Running complete environment setup and validation...$(NC)"
	$(MAKE) setup
	$(MAKE) validate
	@echo "$(GREEN)🎉 Complete setup and validation finished!$(NC)"

dev-cycle: ## Workflow: Complete development cycle (format, lint, test)
	@echo "$(BLUE)Running complete development cycle...$(NC)"
	$(MAKE) format
	$(MAKE) lint  
	$(MAKE) check-types
	$(MAKE) test-unit
	@echo "$(GREEN)Development cycle completed$(NC)"

production-check: ## Workflow: Production readiness validation
	@echo "$(BLUE)Running production readiness checks...$(NC)"
	$(MAKE) validate
	$(MAKE) test-coverage
	$(MAKE) lint
	$(MAKE) check-types
	@echo "$(GREEN)Production readiness validated$(NC)"

# =============================================================================
# Utility Commands
# =============================================================================

shell-postgres: ## Utility: Open PostgreSQL shell
	$(COMPOSE_CMD) exec postgres psql -U seo -d seo_platform

shell-redis: ## Utility: Open Redis CLI
	$(COMPOSE_CMD) exec redis redis-cli

shell-nats: ## Utility: Open NATS CLI (if available)
	$(COMPOSE_CMD) exec nats nats account info

backup-db: ## Utility: Backup PostgreSQL database
	@echo "$(BLUE)Creating database backup...$(NC)"
	@mkdir -p backups
	$(COMPOSE_CMD) exec postgres pg_dump -U seo seo_platform > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)Database backup created in backups/$(NC)"

status: ## Utility: Show system status
	@echo "$(BLUE)=== Docker Services Status ===$(NC)"
	$(COMPOSE_CMD) ps
	@echo ""
	@echo "$(BLUE)=== Health Check ===$(NC)"
	$(MAKE) health

# Performance and Profiling
test-profile: ## Run tests with profiling
	@echo "$(BLUE)Running tests with profiling...$(NC)"
	$(PYTEST) tests/ --profile -v

test-benchmark: ## Run performance benchmark tests
	@echo "$(BLUE)Running benchmark tests...$(NC)"
	$(PYTEST) tests/ -m "benchmark" -v

# Export Commands  
test-junit: ## Generate JUnit XML report for CI
	@echo "$(BLUE)Generating JUnit XML report...$(NC)"
	$(PYTEST) tests/ --junitxml=junit.xml -v

# Environment Validation
test-env: ## Test environment configuration
	@echo "$(BLUE)Testing environment configuration...$(NC)"
	$(PYTHON) validate_config.py
	@echo "$(GREEN)Environment configuration is valid$(NC)"

# Help for specific test files
test-file: ## Run tests for a specific file (usage: make test-file FILE=path/to/test_file.py)
	@test -n "$(FILE)" || (echo "$(RED)Usage: make test-file FILE=path/to/test_file.py$(NC)" && exit 1)
	@echo "$(BLUE)Running tests for $(FILE)...$(NC)"  
	$(PYTEST) $(FILE) -v
	
# Watch mode (requires pytest-watch)
test-watch: ## Watch files and re-run tests on changes
	@echo "$(BLUE)Starting test watch mode...$(NC)"
	@echo "$(YELLOW)Note: Install pytest-watch with 'pip install pytest-watch'$(NC)"
	ptw tests/ --runner "$(PYTEST) -v"