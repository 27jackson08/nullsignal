"""Provenance for every file the store reads.

The snapshot manifest is the project's own answer to "where did this come
from", and a system arguing that unattributed data is the problem cannot have
gaps in its own record.

It had four. A partial snapshot used to overwrite the manifest wholesale rather
than merging into it; that was fixed, but the entries already lost never came
back, so the census geometry, the vulnerability index, the weather forecast and
the transit feed health were all read by the store and declared nowhere -- two
of them the critical sources, and one the basis of every equity claim here.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
STORE = Path(__file__).resolve().parents[1] / "src" / "nullsignal" / "store.py"

pytestmark = pytest.mark.skipif(
    not (RAW / "manifest.json").exists(), reason="needs a snapshot")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((RAW / "manifest.json").read_text())


def read_bytes(name: str) -> bytes | None:
    path = RAW / name
    gz = path.with_suffix(path.suffix + ".gz")
    real = path if path.exists() else gz if gz.exists() else None
    if real is None:
        return None
    return gzip.decompress(real.read_bytes()) if real.suffix == ".gz" else real.read_bytes()


def test_every_declared_hash_matches_the_committed_file(manifest):
    """The manifest is a claim about bytes on disk. Check the bytes."""
    for source in manifest["sources"]:
        data = read_bytes(source["path"])
        assert data is not None, f"{source['source_id']} declares a file that is not here"
        assert hashlib.sha256(data).hexdigest()[:16] == source["content_hash"], (
            f"{source['source_id']} does not hash to its declared value"
        )
        assert len(data) == source["byte_count"]


def test_every_file_the_store_reads_has_provenance(manifest):
    """A source read but never declared is exactly the gap this project names.

    Parsed out of `store.py` rather than listed here, so adding a loader
    without recording where its data came from fails instead of passing
    quietly.
    """
    read = set(re.findall(r'raw_dir / "([^"]+)"', STORE.read_text()))
    assert read, "found no sources being read; the pattern needs updating"

    declared = {s["path"] for s in manifest["sources"]}
    declared |= {p + ".gz" for p in declared}

    undeclared = {
        name for name in read
        if name not in declared and f"{name}.gz" not in declared
        and read_bytes(name) is not None
    }
    assert not undeclared, (
        f"the store reads {sorted(undeclared)} with no entry in the manifest, "
        f"so the interface shows a provenance record that omits them"
    )


def test_reconstructed_entries_do_not_invent_a_fetch_time(manifest):
    """Where the timestamp was lost, it stays lost.

    Filling it with the file's mtime, or with now, would be a fabricated
    measurement sitting in the record whose whole job is to be trustworthy.
    """
    for source in manifest["sources"]:
        if "reconstructed" in (source.get("note") or ""):
            assert source["fetched_at"] is None, (
                f"{source['source_id']} carries a fetch time it cannot know"
            )
