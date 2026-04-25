.PHONY: help install dev run lint format typecheck test test-cov clean db-init

help:
	@echo "make install   — установить зависимости (prod)"
	@echo "make dev       — установить зависимости (dev)"
	@echo "make run       — запустить бот"
	@echo "make lint      — ruff проверка"
	@echo "make format    — ruff format + auto-fix"
	@echo "make typecheck — mypy"
	@echo "make test      — pytest"
	@echo "make test-cov  — pytest + coverage"
	@echo "make db-init   — создать таблицы БД"
	@echo "make clean     — удалить кэши"

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements-dev.txt

run:
	python -m main

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy --config-file pyproject.toml .

test:
	pytest -v

test-cov:
	pytest --cov=. --cov-report=term-missing --cov-report=xml

db-init:
	python -m db.init_db

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
