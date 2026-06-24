#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class SmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    company_id: int
    user_id: str
    bearer_token: str | None
    use_auth_token_flow: bool
    timeout_seconds: float


def _bool_from_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _base_url_from_env(env: Mapping[str, str]) -> str:
    raw = (env.get("SMOKE_BASE_URL") or env.get("BASE_URL") or "").strip()
    if not raw:
        raise SmokeError("Missing SMOKE_BASE_URL (or BASE_URL)")
    return raw.rstrip("/")


def load_config(env: Mapping[str, str]) -> SmokeConfig:
    base_url = _base_url_from_env(env)

    company_id_raw = (env.get("SMOKE_COMPANY_ID") or env.get("COMPANY_ID") or "").strip()
    if not company_id_raw:
        raise SmokeError("Missing SMOKE_COMPANY_ID (or COMPANY_ID)")
    try:
        company_id = int(company_id_raw)
    except ValueError as exc:
        raise SmokeError("SMOKE_COMPANY_ID must be an integer") from exc

    user_id = (env.get("SMOKE_USER_ID") or env.get("USER_ID") or "smoke-user").strip()
    if not user_id:
        raise SmokeError("SMOKE_USER_ID must be non-empty")

    bearer_token = (env.get("SMOKE_BEARER_TOKEN") or "").strip() or None
    use_auth_token_flow = _bool_from_env(env.get("SMOKE_USE_AUTH_TOKEN_FLOW"), default=True)

    timeout_raw = (env.get("SMOKE_TIMEOUT_SECONDS") or "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise SmokeError("SMOKE_TIMEOUT_SECONDS must be numeric") from exc

    return SmokeConfig(
        base_url=base_url,
        company_id=company_id,
        user_id=user_id,
        bearer_token=bearer_token,
        use_auth_token_flow=use_auth_token_flow,
        timeout_seconds=timeout_seconds,
    )


def _request_json(
    *,
    method: str,
    url: str,
    timeout_seconds: float,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body: bytes | None = None
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, method=method, data=body, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            status = int(resp.getcode())
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        data = exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SmokeError(f"Request failed for {method} {url}: {exc}") from exc

    if not data:
        return status, None
    try:
        return status, json.loads(data)
    except json.JSONDecodeError:
        return status, data


def _endpoint(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return f"{base_url}{path}"
    query = urllib.parse.urlencode(params)
    return f"{base_url}{path}?{query}"


def _require_2xx(status: int, name: str) -> None:
    if status < 200 or status >= 300:
        raise SmokeError(f"{name} failed with HTTP {status}")


def _acquire_token(config: SmokeConfig) -> str:
    if not config.use_auth_token_flow:
        if config.bearer_token is None:
            raise SmokeError("SMOKE_BEARER_TOKEN is required when SMOKE_USE_AUTH_TOKEN_FLOW is disabled")
        return config.bearer_token

    status, body = _request_json(
        method="POST",
        url=_endpoint(config.base_url, "/auth/token"),
        timeout_seconds=config.timeout_seconds,
        payload={"user_id": config.user_id, "company_id": config.company_id},
    )
    _require_2xx(status, "auth token endpoint")
    token = body.get("access_token") if isinstance(body, dict) else None
    if not token or not isinstance(token, str):
        raise SmokeError("auth token endpoint did not return access_token")
    return token


def _check_health_or_status(config: SmokeConfig) -> str | None:
    for path in ("/health", "/status"):
        status, _ = _request_json(
            method="GET",
            url=_endpoint(config.base_url, path),
            timeout_seconds=config.timeout_seconds,
        )
        if status == 200:
            return path
        if status != 404:
            raise SmokeError(f"health/status check failed at {path} with HTTP {status}")
    return None


def _authenticated_headers(company_id: int, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _authenticated_get(
    *,
    config: SmokeConfig,
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    return _request_json(
        method="GET",
        url=_endpoint(config.base_url, path, params),
        timeout_seconds=config.timeout_seconds,
        headers=_authenticated_headers(config.company_id, token),
    )


def run_smoke(config: SmokeConfig) -> None:
    print(f"SMOKE_BASE_URL={config.base_url}")
    print(f"SMOKE_COMPANY_ID={config.company_id}")

    health_path = _check_health_or_status(config)
    if health_path is None:
        print("HEALTH_STATUS_CHECK=SKIPPED (no /health or /status endpoint)")
    else:
        print(f"HEALTH_STATUS_CHECK=OK ({health_path})")

    token = _acquire_token(config)
    print(f"AUTH_TOKEN=OK len={len(token)}")

    checks: list[tuple[str, str, dict[str, Any] | None]] = [
        ("payroll runs list", "/payroll/runs", {"limit": 5, "offset": 0}),
        ("invoice list", "/invoices", None),
        ("waste-bin service ticket queue", "/waste-bin/service-tickets/queue", None),
        ("PO queue", "/job-documents/purchase-orders/queue", None),
    ]

    for name, path, params in checks:
        status, _ = _authenticated_get(
            config=config,
            token=token,
            path=path,
            params=params,
        )
        _require_2xx(status, name)
        print(f"CHECK_OK {name} ({path})")

    print("LIVE_SMOKE_PASSED")


def main(argv: list[str]) -> int:
    try:
        config = load_config(os.environ)
        run_smoke(config)
        return 0
    except SmokeError as exc:
        print(f"LIVE_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
