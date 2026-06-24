# Production Rollout Checklist (DigitalOcean App Platform)

This checklist is for safe, repeatable production releases of `frontier_backend`.

## 1) Pre-Deploy Checks

1. Ensure local test baseline is green:

```bash
./scripts/test_local.sh
```

2. Confirm deployment credentials are available in your shell:

```bash
env | rg 'DO_API_TOKEN|DO_APP_ID|SMOKE_BASE_URL|SMOKE_COMPANY_ID|SMOKE_BEARER_TOKEN|SMOKE_USE_AUTH_TOKEN_FLOW|SMOKE_USER_ID'
```

3. For production smoke auth, prefer bearer token mode:

- Set `SMOKE_BEARER_TOKEN` and do **not** rely on `/auth/token` in production.
- Use `SMOKE_USE_AUTH_TOKEN_FLOW=true` only in non-prod environments where `/auth/token` is enabled.

4. Verify GitHub Actions secrets are set (for workflow-based deploy):

- `DO_API_TOKEN`
- `DO_APP_ID`
- `SMOKE_BASE_URL`
- `SMOKE_COMPANY_ID`
- `SMOKE_BEARER_TOKEN` (recommended for prod)
- `SMOKE_USER_ID` (required only if token flow is used)

## 2) Deploy Command (CLI)

```bash
export DO_API_TOKEN="dop_v1_xxx"
export DO_APP_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
./scripts/do_app_deploy.sh
```

Optional:

```bash
export DEPLOY_TIMEOUT_SECONDS="1200"
export DEPLOY_POLL_SECONDS="10"
export RUN_LIVE_SMOKE="1"  # run smoke immediately after ACTIVE
./scripts/do_app_deploy.sh
```

## 3) Smoke Test Command (Post-Deploy)

Recommended production mode (bearer token):

```bash
export SMOKE_BASE_URL="https://your-app.ondigitalocean.app"
export SMOKE_COMPANY_ID="1"
export SMOKE_BEARER_TOKEN="<prod-smoke-token>"
./scripts/live_smoke.py
```

Non-production token flow mode:

```bash
export SMOKE_BASE_URL="https://your-nonprod-url"
export SMOKE_COMPANY_ID="1"
export SMOKE_USE_AUTH_TOKEN_FLOW="true"
export SMOKE_USER_ID="smoke-user"
./scripts/live_smoke.py
```

Smoke verifies:

- `GET /health` or `GET /status` (if present)
- `POST /auth/token` (only if token flow enabled)
- `GET /payroll/runs`
- `GET /invoices`
- `GET /waste-bin/service-tickets/queue`
- `GET /job-documents/purchase-orders/queue`

## 4) Rollback Notes

If deploy fails smoke or critical checks:

1. Identify last known good deployment ID:

```bash
doctl apps list-deployments "$DO_APP_ID"
```

2. In DigitalOcean App Platform UI, rollback to the previous healthy deployment/revision.

3. Re-run smoke checks against production URL:

```bash
./scripts/live_smoke.py
```

4. Freeze further deploys until root cause is identified.

## 5) Post-Deploy Verification

1. Confirm deploy reached `ACTIVE`.
2. Confirm `LIVE_SMOKE_PASSED`.
3. Check DigitalOcean runtime logs for startup errors.
4. Verify key business APIs are responsive from smoke output.
5. Record deployment ID, timestamp, and smoke result in release notes.

## Required Environment Variables

- Deploy helper:
  - `DO_API_TOKEN` (required)
  - `DO_APP_ID` (required)
- Smoke runner:
  - `SMOKE_BASE_URL` (or `BASE_URL`) required
  - `SMOKE_COMPANY_ID` (or `COMPANY_ID`) required
  - Auth option A: `SMOKE_BEARER_TOKEN`
  - Auth option B: `SMOKE_USE_AUTH_TOKEN_FLOW=true` (+ optional `SMOKE_USER_ID`)
  - Optional: `SMOKE_TIMEOUT_SECONDS`
