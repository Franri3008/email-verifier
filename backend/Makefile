.PHONY: install run test lint format
PYTHON ?= ../.venv/bin/python

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn app.main:app --reload --port 8000 --no-access-log

test:
	$(PYTHON) -m pytest tests -v

lint:
	$(PYTHON) -m ruff check app tests

format:
	$(PYTHON) -m ruff format app tests
