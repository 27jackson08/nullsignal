.PHONY: help setup snapshot build test serve web demo check

help:
	@echo "NullSignal"
	@echo ""
	@echo "  make demo      build if needed, then run engine + web       <- start here"
	@echo "  make eval      run the canonical scenario and print the scoreboard"
	@echo ""
	@echo "  make setup     install engine + web dependencies"
	@echo "  make snapshot  refresh all public sources into data/raw"
	@echo "  make build     build the DuckDB store from data/raw"
	@echo ""
	@echo "  make test      run the suite"
	@echo "  make coverage  run the suite with a coverage report"
	@echo "  make check     tests, typecheck, and a production build"
	@echo ""
	@echo "A fresh clone needs only: make setup && make build && make demo"
	@echo "The committed snapshot means none of that touches the network."

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

coverage:
	uv run pytest --cov=nullsignal --cov-report=term-missing

# The root tsconfig is a project-references stub: `tsc --noEmit` against it
# passes while the real build fails. Check the app project directly.
check: test
	cd web && npx tsc --noEmit -p tsconfig.app.json
	cd web && npm run build

eval:
	uv run nullsignal eval

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
