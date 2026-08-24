.PHONY: help setup snapshot build test serve web demo check

help:
	@echo "NullSignal"
	@echo "  make setup     install engine + web dependencies"
	@echo "  make snapshot  fetch all public sources into data/raw"
	@echo "  make build     build the DuckDB store from data/raw"
	@echo "  make test      run the invariant suite"
	@echo "  make demo      build if needed, then run engine + web"

setup:
	uv venv
	uv pip install -e ".[dev]"
	cd web && npm install

snapshot:
	uv run nullsignal snapshot

build:
	uv run nullsignal build

test:
	uv run pytest -v

check: test
	cd web && npx tsc --noEmit

serve:
	uv run nullsignal serve

web:
	cd web && npm run dev

data/nullsignal.duckdb: data/raw/manifest.json
	uv run nullsignal build

demo: data/nullsignal.duckdb
	@echo "engine  -> http://127.0.0.1:8000/api/summary"
	@echo "web     -> http://127.0.0.1:5173"
	@trap 'kill 0' EXIT; \
	 uv run nullsignal serve & \
	 (cd web && npm run dev) & \
	 wait
