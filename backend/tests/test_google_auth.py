"""
Google ID-token verification, tested in-process with a throwaway RSA key standing in for Google's.
Needs MONGO_URL / DB_NAME in the environment (app.core.config reads them at import).
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import auth

CLIENT_ID = "test-client.apps.googleusercontent.com"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_IDS", [CLIENT_ID])
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=_key.public_key()))
    monkeypatch.setattr(auth, "_google_jwks", fake_jwks)


def _token(key=_key, **overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "email": "Rider@Example.com",
        "email_verified": True,
        "name": "Rider",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


def _rejects(token, status=401):
    with pytest.raises(HTTPException) as e:
        auth.verify_google_id_token(token)
    assert e.value.status_code == status


def test_valid_token_returns_claims():
    claims = auth.verify_google_id_token(_token())
    assert claims["email"] == "Rider@Example.com"


def test_rejects_other_apps_token():
    _rejects(_token(aud="someone-elses-app"))


def test_rejects_expired_token():
    _rejects(_token(exp=int(time.time()) - 60))


def test_rejects_wrong_issuer():
    _rejects(_token(iss="https://evil.example.com"))


def test_rejects_unverified_email():
    _rejects(_token(email_verified=False))


def test_rejects_token_not_signed_by_google():
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _rejects(_token(key=forged_key))


def test_not_configured_returns_503(monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_IDS", [])
    _rejects(_token(), status=503)
