# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo for a Vietnamese network-anomaly monitoring system (university data-mining project). It ingests Cloudflare Radar time series for `location=VN`, runs analysis/clustering/prediction, and shows the results on a dashboard. `README.md` is the full design spec (in Vietnamese). `CONTRIBUTING.md` has the team workflow. Code comments, docs and commit messages are in Vietnamese or English, so match the surrounding file.

## Commands

The whole stack runs in Docker. There is no local Python or Node setup, and tests also run in Docker.

```bash
cp .env.example .env              # then fill in CF_API_TOKEN etc.
make up                           # docker compose up -d --build (9 containers)
make down                         # keep volumes; `down -v` forces a re-init of DB schemas and a full re-backfill
make logs | make ps
make psql-warehouse | make psql-mart
make reset-mart                   # TRUNCATE the gold tables (demo step 4)

# Ingestion tests; extra args go to pytest
bash services/ingestion/tests/run.sh
bash services/ingestion/tests/run.sh services/ingestion/tests/test_rescale.py -k name
INTEGRATION=1 bash services/ingestion/tests/run.sh   # also runs DB tests against the running warehouse-db (needs .env)

# API tests: Docker only, private test databases/network, no project .env required
bash services/api/tests/run.sh unit          # JWT/query/proxy unit tests
bash services/api/tests/run.sh integration   # also PostgreSQL/runner tests
bash services/api/tests/run.sh all           # also real Keycloak + API/service containers
# Windows PowerShell equivalents:
./services/api/tests/run.ps1 -Mode Unit
./services/api/tests/run.ps1 -Mode Integration
./services/api/tests/run.ps1 -Mode All
# Or: make test-api / make test-api-unit / make test-api-integration

# Frontend build (Node/npm run inside the Docker build)
docker compose build frontend
```

API runner scripts build sequentially to limit peak RAM and clean up their own `kpdl-api-tests-*` project. Test PostgreSQL uses tmpfs; no host ports or production volumes are exposed. `services/api/tests/compose.yml` is independent of the application Compose file. `all` verifies the auth/trigger/journal contracts, not the correctness of unfinished Analysis/ML algorithms or the frontend.

`.github/workflows/backend-api.yml` runs the same Docker suite for backend PRs to develop. It uses no application secrets. See `docs/backend-api-local.md` for commands and `docs/backend-integration-handoff.md` for cross-service review points.

Other services without a runner still import modules flat (`from features import ...`). Run their tests in Docker with the service directory and `backend` on `PYTHONPATH`. Do not collect API and ingestion tests in one pytest process: both use flat module names such as `main`.

DB init scripts in `db/*/init/` only run on an empty volume. Existing databases need an explicit migration or deliberate re-initialization. Never use `docker compose down -v` against application data merely to run tests; the API test runner creates and removes its own disposable databases.

## Architecture

Medallion data flow across two separate PostgreSQL instances:

```
Cloudflare Radar -> ingestion -> warehouse-db (bronze raw JSON -> silver.metrics_hourly)
                                      | read Silver
              analysis / clustering / prediction  -> mart-db (gold.*) -> api (read-only) -> frontend
                                      keycloak (OIDC) <- api verifies JWT, frontend logs in via Auth.js
```

Rules that span several files:

- **Write boundaries are enforced with per-service Postgres users** (see `db/*/init/02-users.sh` and the DSNs in `docker-compose.yml`):
  - `ingestion_user` writes bronze and silver.
  - `logic_user` reads silver and writes gold.
  - `api_user` only has SELECT on gold.
  - Services never call each other for data. The only exception is the API triggering `POST /run` on the logic services.
- **The frontend only draws charts.** All computation happens in the backend. Chart data is fetched from the browser (client components, SWR), not in server components. This is deliberate, so requests show up in the DevTools Network tab during the demo.
- **Empty gold tables make the API return 404.** This is intentional (demo step 5), not a bug.
- **Models are trained offline** (`training/train_models.py` writes `.pkl` files and `metrics.json` to `models/`). The logic services only load them and never train at runtime.
- **Time zones:** store UTC (`TIMESTAMPTZ`). Convert to `Asia/Ho_Chi_Minh` only when bucketing by hour, weekday or "tomorrow".

### Shared service skeleton

Every Python service has the same shape:
- Analysis/ML and ingestion `main.py` call `backend/common/runner.py:create_service_app(name, job, schedule)`. This gives `/health`, an authenticated `/run` returning 202, and APScheduler. The public API has its own app with `/health`, `/ready` and `/api/*` routes.
- `tasks.py` holds the job logic.
- The Dockerfile copies `backend/common` to `/app/common` and the service directory to `/app`, with `PYTHONPATH=/app`. So service modules import each other **flat** (`from pipeline import ...`) and shared code is imported as `common.*`.
- Build context is the repo root (see `docker-compose.yml`).
- Config comes from env vars through `common.config.settings` (pydantic-settings).
- `SCHEDULER_ENABLED=false` disables APScheduler, which tests rely on.

Changing `backend/common/` affects every Python service.

For Analysis/Clustering/Prediction, `common.runner` owns `gold.service_runs`; tasks must not write duplicate run logs. Manual Run and scheduler share a local lock plus a PostgreSQL advisory lock per service. A 202 is acceptance, not successful computation: poll the returned ID at `/api/jobs/runs/{run_id}` (admin). `/api/status` only returns the latest run per service. Ingestion retains its own Warehouse run log and backfill lock. `JOB_TRIGGER_TOKEN` protects the internal endpoints and must match API/logic services when auth is enabled.

### Implementation status

- **Implemented in this backend branch:** Gold read APIs, response validation/pagination, `/api/me`, Keycloak JWT/JWKS and Viewer/Admin, admin Jobs API and the shared execution/journal/lock mechanism. See `docs/api-contract.md` and `docs/backend-auth-jobs.md`.
- **Implemented:** `ingestion`, with its tests.
- Analysis/ML tasks and training in the active checkout must be inspected before assuming they exist. Separate feature branches may be ahead of develop. Do not merge their code just to make backend tests pass. Current unimplemented tasks report a failed run rather than fabricated success.
- Frontend has separate demo and live API modes. Live mode uses NextAuth/Keycloak, backend-validated roles, refresh and exact run tracking. It requires `AUTH_ENABLED=true`. See `docs/frontend-live-integration.md`; algorithm/data acceptance remains separate.
- Check the code before assuming a README feature exists.

### Ingestion service (`services/ingestion/`)

Read `services/ingestion/README.md` before changing it. The non-obvious parts:

- **Per-window rescaling.** Radar's `MIN0_MAX` normalization is computed per query window, so the same hour has different values in different calls. `rescale.py` multiplies each new window by `k = median(silver / new)` over the overlap (needs at least 12 overlapping points). Silver values can therefore exceed 1 (about 1.31 seen), which is expected. `bot_share` and `human_share` are percentages and are not rescaled.
- **Never write unscaled data.** If a window has no usable overlap, it is skipped and not written. After more than ~36 h of downtime the polling window widens, up to 28 days. Beyond that a manual backfill is needed.
- **Two writers share one lock.** The 5-minute cycle (`run_cycle`, `dateRange=2d`) and the background backfill (`backfill.py`, newest to oldest, 28-day chunks, 2-day overlap, resumable) both use `ingest_lock`. The cycle skips while a backfill is running.
- **Write path per endpoint and window:** API call, raw JSON into `bronze.raw_api_responses`, parse, rescale, idempotent upsert into `silver.metrics_hourly` (`ON CONFLICT (ts, metric)`). Each cycle logs a row in `silver.ingestion_runs` as `success`, `partial` or `failed`, and one failing endpoint must not abort the cycle.
- The `CF_API_TOKEN` must never be logged.
- Tests use JSON fixtures in `tests/fixtures/`. Tests marked `integration` need `TEST_WAREHOUSE_DSN` and roll back their transaction.

### Frontend (`frontend/`)

Next.js 16 App Router, React 19, Tailwind 4, ECharts via `echarts-for-react`, SWR and next-auth 4 with a Keycloak provider. API calls go through `lib/api.ts`, and response types are in `types/api.ts`. Demo mode is the default. For live sessions use `NEXT_PUBLIC_DATA_MODE=api` plus `AUTH_ENABLED=true`, then rebuild frontend: public variables are embedded at build time. Docker frontend builds run the Node unit tests and ESLint before Next.js build.

`AUTH_ENABLED=false` grants the development identity viewer/admin permissions; it must not be used to accept authentication. In API mode, Auth.js must provide the access token, handle refresh and forward Authorization from browser requests. Gold histogram/seasonal/correlation snapshots and current status reject start/end with 422; do not send dashboard date filters to these endpoints. DB nullable/non-finite measurements are returned as null, never fabricated zeroes.

### Auth gotcha

The browser reaches Keycloak at `localhost:8080`, but the API container reaches it at `keycloak:8080`. `KC_HOSTNAME` and `KEYCLOAK_ISSUER` must match so the token `iss` claim validates. A mismatch shows up as 401s from the API.

JWT verifies RS256, public issuer, audience `cyber-radar-api`, time claims and access-token type. `KEYCLOAK_JWKS_URL` is a separate internal URL in Docker; changing its connection destination must not change or disable issuer/audience checks. The Docker E2E test transport maps the public issuer to an internal connection while preserving Host/cookie origin and token validation.

## Workflow conventions (CONTRIBUTING.md and issue #2)

- Never push directly to `main` or `develop`. Use feature branches and PRs targeting `develop` (squash-merge), one concern per PR; `develop` targets `main` only for release.
- Branches are `<type>/<service>-<short-desc>`. Commits are Conventional Commits with the service in parentheses, for example `feat(ingestion): ...`. Valid scopes are `ingestion`, `analysis`, `clustering`, `prediction`, `api`, `fe`, `db`, `keycloak`, `common`, `training`, `docker`, `ci`, `readme`.
- New env vars go in `.env.example` with fake values. Never commit `.env`.
- Changing a DB schema or an API JSON shape needs a heads-up to the service owners in the PR. API endpoint changes also update the endpoint table in `README.md`.
