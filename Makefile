.PHONY: install run run-backend run-frontend test lint format

install:
	python3 -m venv .venv
	cd backend && $(MAKE) install
	cd frontend && $(MAKE) install

run:
	$(MAKE) -j2 run-backend run-frontend

setup:
	.venv/bin/python scripts/setup_local.py

run-backend:
	cd backend && $(MAKE) run

run-frontend:
	cd frontend && $(MAKE) run

test:
	cd backend && $(MAKE) test
	cd frontend && $(MAKE) test

lint:
	cd backend && $(MAKE) lint
	cd frontend && $(MAKE) lint

format:
	cd backend && $(MAKE) format
