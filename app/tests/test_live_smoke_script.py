from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from urllib.parse import urlparse

import pytest


def _load_live_smoke_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "live_smoke.py"
    spec = importlib.util.spec_from_file_location("live_smoke_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_smoke_load_config_from_env_with_bearer_token():
    live_smoke = _load_live_smoke_module()

    cfg = live_smoke.load_config(
        {
            "SMOKE_BASE_URL": "https://api.example.com/",
            "SMOKE_COMPANY_ID": "42",
            "SMOKE_USER_ID": "ops-smoke",
            "SMOKE_BEARER_TOKEN": "token-abc",
            "SMOKE_USE_AUTH_TOKEN_FLOW": "false",
            "SMOKE_TIMEOUT_SECONDS": "7.5",
        }
    )

    assert cfg.base_url == "https://api.example.com"
    assert cfg.company_id == 42
    assert cfg.user_id == "ops-smoke"
    assert cfg.bearer_token == "token-abc"
    assert cfg.use_auth_token_flow is False
    assert cfg.timeout_seconds == 7.5


def test_live_smoke_requires_token_when_auth_flow_disabled_without_bearer_token():
    live_smoke = _load_live_smoke_module()
    cfg = live_smoke.SmokeConfig(
        base_url="https://api.example.com",
        company_id=1,
        user_id="smoke",
        bearer_token=None,
        use_auth_token_flow=False,
        timeout_seconds=5.0,
    )

    with pytest.raises(live_smoke.SmokeError):
        live_smoke._acquire_token(cfg)


def test_live_smoke_run_checks_required_endpoints_and_allows_missing_health(monkeypatch):
    live_smoke = _load_live_smoke_module()
    cfg = live_smoke.SmokeConfig(
        base_url="https://api.example.com",
        company_id=9,
        user_id="smoke",
        bearer_token="existing-token",
        use_auth_token_flow=False,
        timeout_seconds=5.0,
    )

    calls: list[tuple[str, str]] = []

    def fake_request_json(*, method, url, timeout_seconds, payload=None, headers=None):
        path = urlparse(url).path
        calls.append((method, path))

        if path in {"/health", "/status"}:
            return 404, {"detail": "not found"}

        allowed = {
            "/payroll/runs",
            "/invoices",
            "/waste-bin/service-tickets/queue",
            "/job-documents/purchase-orders/queue",
        }
        if path in allowed:
            return 200, []

        raise AssertionError(f"Unexpected request path: {path}")

    monkeypatch.setattr(live_smoke, "_request_json", fake_request_json)

    live_smoke.run_smoke(cfg)

    assert ("GET", "/payroll/runs") in calls
    assert ("GET", "/invoices") in calls
    assert ("GET", "/waste-bin/service-tickets/queue") in calls
    assert ("GET", "/job-documents/purchase-orders/queue") in calls


def test_live_smoke_run_uses_token_from_auth_flow_for_authenticated_requests(monkeypatch):
    live_smoke = _load_live_smoke_module()
    cfg = live_smoke.SmokeConfig(
        base_url="https://api.example.com",
        company_id=1,
        user_id="smoke-user",
        bearer_token="stale-token",
        use_auth_token_flow=True,
        timeout_seconds=5.0,
    )

    auth_token = "fresh-token-from-auth"
    auth_payloads: list[dict[str, object]] = []
    payroll_auth_headers: list[dict[str, str]] = []

    def fake_request_json(*, method, url, timeout_seconds, payload=None, headers=None):
        path = urlparse(url).path

        if path in {"/health", "/status"}:
            return 200, {"ok": True}

        if path == "/auth/token":
            assert method == "POST"
            assert payload is not None
            auth_payloads.append(payload)
            return 200, {"access_token": auth_token}

        if path == "/payroll/runs":
            assert method == "GET"
            assert headers is not None
            payroll_auth_headers.append(headers)
            return 200, []

        allowed = {
            "/invoices",
            "/waste-bin/service-tickets/queue",
            "/job-documents/purchase-orders/queue",
        }
        if path in allowed:
            return 200, []

        raise AssertionError(f"Unexpected request path: {path}")

    monkeypatch.setattr(live_smoke, "_request_json", fake_request_json)

    live_smoke.run_smoke(cfg)

    assert auth_payloads == [{"user_id": "smoke-user", "company_id": 1}]
    assert payroll_auth_headers
    assert payroll_auth_headers[0]["Authorization"] == f"Bearer {auth_token}"
    assert payroll_auth_headers[0]["X-Company-Id"] == "1"
