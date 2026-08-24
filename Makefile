.PHONY: help install test lint typecheck compose-config up down

help:
	@echo "Available targets: install test lint typecheck compose-config up down"

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check .

typecheck:
	mypy .

compose-config:
	docker compose config

up:
	docker compose up -d --build

down:
	docker compose down

