PYTHON ?= python3

.PHONY: install lint format test run docker-build docker-up docker-down

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

lint:
	ruff check app tests

format:
	black app tests

test:
	pytest

run:
	$(PYTHON) -m app.main --run-once

docker-build:
	docker build -t obsidian2confluence:latest .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
