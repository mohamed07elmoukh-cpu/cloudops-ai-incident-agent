.PHONY: help test

help:
	@echo "Available targets: test"

test:
	python -m pytest

