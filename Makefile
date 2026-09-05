.PHONY: help install test lint typecheck dashboard-install dashboard-test dashboard-build compose-config up down

help:
	@echo "Available targets: install test lint typecheck dashboard-install dashboard-test dashboard-build compose-config up down"

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check .

typecheck:
	mypy .

dashboard-install:
	npm --prefix apps/dashboard install

dashboard-test:
	npm --prefix apps/dashboard run test:e2e

dashboard-build:
	npm --prefix apps/dashboard run build

compose-config:
	docker compose config

up:
	docker compose up -d --build

down:
	docker compose down
