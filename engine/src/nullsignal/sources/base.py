"""Fetch primitives shared by every source adapter.

Every fetch records a content hash and a wall-clock timestamp. Those two fields
are what the reliability layer later uses to notice a feed that is technically
up and semantically dead, so they are captured at ingest rather than bolted on.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

# NWS rejects requests without a contact in the User-Agent, so every adapter
# sends one. Other hosts simply ignore it.
USER_AGENT = "nullsignal-research (https://github.com/27jackson08/nullsignal)"

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class SourceFetchError(RuntimeError):
    """Raised when a source cannot be fetched. Never swallowed silently -- a
    system about missing data must not lose its own data quietly."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    source_id: str
    fetched_at: datetime
    status_code: int
    content_hash: str
    byte_count: int
    path: Path
    note: str = ""

    def as_manifest_entry(self) -> dict:
        return {
            "source_id": self.source_id,
            "fetched_at": self.fetched_at.isoformat(),
            "status_code": self.status_code,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "path": str(self.path.name),
            "note": self.note,
        }


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def fetch_to_file(
    source_id: str,
    url: str,
    dest: Path,
    *,
    params: dict | None = None,
    note: str = "",
) -> FetchResult:
    """GET a URL and write the body to disk, recording provenance."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SourceFetchError(f"{source_id}: request failed for {url}: {exc}") from exc

    if response.status_code != 200:
        raise SourceFetchError(
            f"{source_id}: HTTP {response.status_code} from {url} "
            f"({response.text[:180]})"
        )

    payload = response.content
    dest.write_bytes(payload)
    return FetchResult(
        source_id=source_id,
        fetched_at=datetime.now(UTC),
        status_code=response.status_code,
        content_hash=_hash(payload),
        byte_count=len(payload),
        path=dest,
        note=note,
    )


def write_json(source_id: str, records: list[dict], dest: Path, *, note: str = "") -> FetchResult:
    """Persist already-assembled records with the same provenance shape."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, separators=(",", ":")).encode()
    dest.write_bytes(payload)
    return FetchResult(
        source_id=source_id,
        fetched_at=datetime.now(UTC),
        status_code=200,
        content_hash=_hash(payload),
        byte_count=len(payload),
        path=dest,
        note=note or f"{len(records)} records",
    )
