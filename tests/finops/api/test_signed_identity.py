from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from app.finops.api import ForbiddenIdentity, resolve_identity


def _signature(secret: str, tenant: str, role: str, request_id: str, timestamp: str) -> str:
    message = f"{tenant}\n{role}\n{request_id}\n{timestamp}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def test_signed_identity_rejects_unsigned_tenant_header(monkeypatch) -> None:
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "signed")
    monkeypatch.setenv("FINOPS_IDENTITY_SECRET", "test-signing-secret")

    with pytest.raises(ForbiddenIdentity, match="signature"):
        resolve_identity("acme", "analyst", "req-1", None, None)


def test_signed_identity_accepts_fresh_valid_signature(monkeypatch) -> None:
    secret = "test-signing-secret"
    timestamp = str(int(time.time()))
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "signed")
    monkeypatch.setenv("FINOPS_IDENTITY_SECRET", secret)
    signature = _signature(secret, "acme", "analyst", "req-1", timestamp)

    identity = resolve_identity(
        "acme", "analyst", "req-1", signature, timestamp
    )

    assert identity.tenant_id == "acme"
    assert identity.role == "analyst"


def test_signed_identity_rejects_stale_signature(monkeypatch) -> None:
    secret = "test-signing-secret"
    timestamp = str(int(time.time()) - 301)
    monkeypatch.setenv("FINOPS_IDENTITY_MODE", "signed")
    monkeypatch.setenv("FINOPS_IDENTITY_SECRET", secret)
    signature = _signature(secret, "acme", "analyst", "req-1", timestamp)

    with pytest.raises(ForbiddenIdentity, match="expired"):
        resolve_identity("acme", "analyst", "req-1", signature, timestamp)
