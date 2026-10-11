PYTHON ?= python

.PHONY: install up down test lint format migrate loadtest

install:
	$(PYTHON) -m pip install -e ".[dev]"

up:
	docker compose up --build

down:
	docker compose down -v

test:
	$(PYTHON) -m pytest --cov=app --cov=worker --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

migrate:
	$(PYTHON) -m alembic upgrade head

loadtest:
	$(PYTHON) -m locust -f loadtest/locustfile.py --host http://localhost:8000
