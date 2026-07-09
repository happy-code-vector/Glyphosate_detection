# PurityIQ / ResidueIQ

A contaminant-residue data pipeline and detection engine for food, water, and
consumer products. Aggregates regulatory and testing data from 30+ government
and independent sources into a queryable database, then exposes a contaminant
risk-scoring API used by the PurityIQ app.

> **For the full technical picture — schema, sources, detection architecture,
> known issues — read [`docs/DATABASE_AND_ENGINE_STATUS.md`](docs/DATABASE_AND_ENGINE_STATUS.md).**

## What this project does

- **Ingests** 30+ data sources (FDA, USDA PDP, EPA CFR, EFSA, Germany BVL, CFIA,
  UK FSA, CA DPR, USGS water, CDC NHANES, certification registries, …) into a
  SQLite database.
- **Resolves** messy commodity names to canonical categories (712 aliases).
- **Scores** contaminant risk via a three-tier model
  (product → ingredient → category) with EPA tolerance first, EFSA MRL fallback,
  and consumption-tier weighting.
- **Exposes** a `DetectionEngine` API (17 methods) covering barcode scans, PLU
  produce lookups, water quality, international MRL comparison, and ingredient
  flags.

## Repository layout

| Path | Purpose |
|------|---------|
| `detect/` | Detection engine (`engine.py`) + data models, ingredient risk, Open Food Facts client |
| `data/` | Data pipeline: fetchers, DB layer (`db/`), seeding, Firestore migration |
| `data/db/schema.sql` | Database schema (16 tables, 5 views) |
| `docs/` | Status doc, design specs, plans |
| `tests/` | Pytest suite (167 tests) |
| `research/` | Data-source research notes |

See [`data/README.md`](data/README.md) for pipeline run instructions and
[`docs/DATABASE_AND_ENGINE_STATUS.md`](docs/DATABASE_AND_ENGINE_STATUS.md) for
architecture, the test suite breakdown, and known issues.

## Setup

```bash
pip install -r requirements.txt
```

## Run the data pipeline

```bash
python run_pipeline.py                 # full pipeline
python run_pipeline.py --source fda    # single source
python run_pipeline.py --validate      # validate DB after a run
```

See `data/README.md` for the full list of sources and flags.

## Tests

```bash
python -m pytest -q
```

> Barcode-scan tests hit the live Open Food Facts API, so a full run takes
> several minutes.

## Architecture decision

The project is **SQLite-only**, behind a `DataStore` Protocol abstraction
(`data/datastore.py`) with a single implementation (`SqliteDataStore`).
Firestore was evaluated and removed — its read latency was too slow for the
detection engine's multi-query scan flow. SQLite serves reads in-process with
no network round-trips.
