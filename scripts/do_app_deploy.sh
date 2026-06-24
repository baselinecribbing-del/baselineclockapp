#!/usr/bin/env bash
set -euo pipefail

: "${DO_APP_ID:?DO_APP_ID is required}"
: "${DO_API_TOKEN:?DO_API_TOKEN is required}"

if ! command -v doctl >/dev/null 2>&1; then
  echo "ERROR: doctl is required but was not found on PATH" >&2
  exit 1
fi

export DIGITALOCEAN_ACCESS_TOKEN="${DO_API_TOKEN}"

WAIT_FOR_DEPLOY="${WAIT_FOR_DEPLOY:-1}"
DEPLOY_TIMEOUT_SECONDS="${DEPLOY_TIMEOUT_SECONDS:-900}"
DEPLOY_POLL_SECONDS="${DEPLOY_POLL_SECONDS:-10}"
RUN_LIVE_SMOKE="${RUN_LIVE_SMOKE:-0}"

start_epoch="$(date +%s)"

echo "Triggering DigitalOcean App Platform deployment for app ${DO_APP_ID}"
DEPLOYMENT_ID="$(doctl apps create-deployment "${DO_APP_ID}" --format ID --no-header | tr -d '[:space:]')"

if [[ -z "${DEPLOYMENT_ID}" ]]; then
  echo "ERROR: failed to obtain deployment id" >&2
  exit 1
fi

echo "DEPLOYMENT_ID=${DEPLOYMENT_ID}"

if [[ "${WAIT_FOR_DEPLOY}" != "1" ]]; then
  echo "WAIT_FOR_DEPLOY=0, skipping deployment wait"
  exit 0
fi

while true; do
  phase_raw="$(doctl apps get-deployment "${DO_APP_ID}" "${DEPLOYMENT_ID}" --format Phase --no-header | tr -d '[:space:]')"
  phase_upper="$(echo "${phase_raw}" | tr '[:lower:]' '[:upper:]')"
  now_epoch="$(date +%s)"
  elapsed="$((now_epoch - start_epoch))"

  echo "Deployment phase=${phase_raw:-unknown} elapsed=${elapsed}s"

  case "${phase_upper}" in
    ACTIVE)
      echo "Deployment reached ACTIVE"
      break
      ;;
    ERROR|FAILED|CANCELED|CANCELLED|SUPERSEDED)
      echo "ERROR: deployment failed with phase=${phase_raw}" >&2
      exit 1
      ;;
    *)
      if (( elapsed >= DEPLOY_TIMEOUT_SECONDS )); then
        echo "ERROR: deployment timed out after ${DEPLOY_TIMEOUT_SECONDS}s" >&2
        exit 1
      fi
      sleep "${DEPLOY_POLL_SECONDS}"
      ;;
  esac
 done

if [[ "${RUN_LIVE_SMOKE}" == "1" ]]; then
  echo "Running live smoke checks"
  ./scripts/live_smoke.py
fi
