from __future__ import annotations

import pytest

from helpers import make_zone


@pytest.fixture
def zone():
    return make_zone()


# --- integration fixtures -----------------------------------------------------
#
# The data snapshot is committed, so the whole ingest path can be exercised for
# real rather than mocked. These are the layers where a silent schema change --
# a renamed Socrata column, a shifted CDC sentinel -- corrupts everything
# downstream while every unit test stays green.

import pytest as _pytest
from pathlib import Path as _Path

REPO_ROOT = _Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"

requires_snapshot = _pytest.mark.skipif(
    not (RAW_DIR / "manifest.json").exists(),
    reason="no committed snapshot; run `uv run nullsignal snapshot`",
)


@_pytest.fixture(scope="session")
def raw_dir() -> _Path:
    return RAW_DIR


@_pytest.fixture(scope="session")
def store_path(tmp_path_factory) -> _Path:
    """A store built from the committed snapshot, once per session."""
    from nullsignal.store import build_store

    if not (RAW_DIR / "manifest.json").exists():
        _pytest.skip("no committed snapshot")

    path = tmp_path_factory.mktemp("store") / "test.duckdb"
    build_store(RAW_DIR, path)
    return path


@_pytest.fixture(scope="session")
def store(store_path):
    from nullsignal.store import connect

    connection = connect(store_path, read_only=True)
    yield connection
    connection.close()
