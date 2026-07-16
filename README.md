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

## Online API (Cloud Run + Firebase App Check)

A FastAPI service in [`api/`](api/) exposes the detection engine over HTTPS so
the mobile app can call it. It deploys to **Cloud Run** (Python container,
`min-instances=1` for no cold starts) and is gated by **Firebase App Check**
(device attestation) so only the app can use it. The DB is **not** baked into
the image; the entrypoint pulls it read-only from GCS at startup.

```
React Native app ── barcode scan + App Check token ──▶ Cloud Run (FastAPI)
   │                                                       │ App Check verify (firebase_admin, ADC)
   │                                                       ├─ DetectionEngine (read-only)
   │                                                       └─ SQLite pulled from gs://… at start
   └─ nightly: GitHub Actions rebuilds DB → GCS → rolls a new revision
```

### Run the API locally

```bash
pip install -r requirements.txt
python -m uvicorn api.main:app --reload          # http://localhost:8000/docs
```

With `REQUIRE_APPCHECK` unset (default), no token is required. FastAPI
serializes the engine's `@dataclass` result types directly, so responses need no
separate schemas.

### Phase 2 — first deploy to Cloud Run

```bash
# 1. Create a bucket and upload the current DB once.
gcloud storage cp data/residueiq.db gs://$BUCKET/residueiq.db

# 2. Deploy from source.
gcloud run deploy residueiq-api --source . \
  --region $REGION --min-instances=1 --max-instances=5 --concurrency=80 \
  --service-account=$RUN_SA \
  --set-env-vars DB_GCS_URI=gs://$BUCKET/residueiq.db,DB_PATH=/app/data/residueiq.db,FIREBASE_PROJECT_ID=$FIREBASE_PROJECT,REQUIRE_APPCHECK=false
```

Grant the Cloud Run runtime service account: **Firebase App Check Token
Verifier** and **Storage Object Viewer** on the bucket. It authenticates via
Application Default Credentials — **no service-account JSON is committed**.

### Phase 3 — enforce App Check

1. Create/select a Firebase project; register the React Native app (iOS + Android
   bundle ids).
2. Enable **App Check** with **Play Integrity** (Android) and **App Attest**
   (iOS), starting in **Log/monitor** mode.
3. Ship the app with `@react-native-firebase/app-check`, sending the token in
   the `X-Firebase-AppCheck` header on every request.
4. After attestation traffic looks healthy for a few days, redeploy with
   `REQUIRE_APPCHECK=true`. Requests missing/holding an invalid token then get
   `401` ([api/security.py](api/security.py)).

### Phase 4 — nightly data refresh

[`.github/workflows/refresh-db.yml`](.github/workflows/refresh-db.yml) rebuilds
the DB, `VACUUM`s it, uploads to GCS, and rolls a new Cloud Run revision (env
bump) so the new revision re-pulls the fresh DB. Configure the GitHub
**variables** (`GCP_PROJECT_ID`, `GCP_REGION`, `CLOUDRUN_SERVICE`, `GCS_BUCKET`)
and **secrets** (`WIF_PROVIDER`, `GCP_SA_EMAIL`) named at the top of the
workflow; auth is Workload Identity Federation (no long-lived keys).

### Phase 5 — React Native app

Lives in a separate repo (Expo + `expo-camera` for barcode scanning +
`@react-native-firebase/app-check`). Screens: Scan → Result (risk badge +
per-contaminant breakdown + source attribution) → Search → About.

### Notes

- **Open Food Facts** rate-limits to ~2 scans/sec per instance (`detect/open_food_facts.py`); raise `max-instances` to scale.
- `app_food_overview` is a heavy view — filtered reads go through the
  parameterized `_FOOD_OVERVIEW_SQL` in `data/sqlite_store.py` (~7 ms, not the
  ~12 s the view costs). See `app-views-slow-for-filtered-reads`.

