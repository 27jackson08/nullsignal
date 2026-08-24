# NullSignal

**Don't confuse silence with safety.**

Most monitoring systems encode *no data* as *no problem*. NullSignal makes
"we don't know" a first-class state that "low risk" cannot collapse into.

## The 2x2

|                      | Sufficiency low | Sufficiency high |
| -------------------- | --------------- | ---------------- |
| **Risk estimate low**  | `UNKNOWN`       | `CONFIRMED_LOW`  |
| **Risk estimate high** | `SUSPECTED`     | `CONFIRMED_HIGH` |

`CONFIRMED_LOW` requires low risk **and** high sufficiency. Silence can never
produce green. See `engine/src/nullsignal/decision.py`.

## Run it

```bash
make setup
make snapshot     # ~2 min, pulls real NYC data into data/raw
make build        # builds data/nullsignal.duckdb
make demo         # engine on :8000, map on :5173
```

## Data sources

All keyless except where noted. Verified 2026-08-24.

| Source | Dataset | Notes |
| --- | --- | --- |
| NYC 311 | Socrata `erm2-nwe9` | ~99% geocoded |
| Census tracts | Socrata `63ge-mke6` | 2,325 tracts, joins to SVI on `geoid` |
| CDC SVI 2022 | `svi.cdc.gov` | tract-level vulnerability |
| MTA GTFS-RT | `api-endpoint.mta.info` | protobuf, 7 subway feeds |
| NWS | `api.weather.gov` | **403s without a contact email in User-Agent** |

Snapshots are committed so the demo runs offline and the evaluation is
reproducible.

## Rendering

The map is `d3-geo` projecting onto a `<canvas>`, with an offscreen colour-index
buffer for hit testing (constant cost regardless of tract count). Two earlier
approaches were tried and rejected:

- **MapLibre GL** — its Web Worker never completes its handshake in this setup
  (reproduced on v5 and v6, dev and production builds, normal and CSP builds),
  so layers render but no source ever parses. With no basemap in the design,
  MapLibre's tile streaming was unused anyway.
- **SVG paths** — 2,325 DOM nodes made every view switch re-render the tree.

Canvas: ~1 ms per view switch, 64 DOM nodes, no long tasks.

## Status

Day 1 of 7 — walking skeleton. See `docs/PLAN.md`.

The suite doubles as a build progress meter: invariants for components not yet
built are skipped with the day they unlock, rather than quietly passing.

```
make test
```
