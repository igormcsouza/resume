import io
import json

import jwt
import pytest

from resume_mcp import citadel

from .conftest import CLIENT_ID, OTHER_KEY, OWNER, FakeJwks, alg_none_token, id_token, settings


def fake_urlopen(token):
    return lambda req, timeout: io.BytesIO(json.dumps({"id_token": token}).encode())


def identify(monkeypatch, token, jwks=None):
    monkeypatch.setattr(citadel.urllib.request, "urlopen", fake_urlopen(token))
    return citadel.identify(settings(), jwks or FakeJwks(), "code", "verifier", "https://api.example.test/oauth/callback")


def test_valid_id_token_gives_the_sub(monkeypatch):
    assert identify(monkeypatch, id_token()) == OWNER


BAD = {
    "wrong audience": lambda: id_token(aud="another-app"),
    "wrong issuer": lambda: id_token(iss="https://evil.example/pool"),
    "access token, not id": lambda: id_token(token_use="access"),
    "expired": lambda: id_token(exp=1),
    "no sub": lambda: id_token(sub=None),
    "signed by other key": lambda: id_token(key=OTHER_KEY),
    "alg none": alg_none_token,
}


@pytest.mark.parametrize("name", BAD)
def test_bad_id_tokens_are_rejected(monkeypatch, name):
    with pytest.raises(jwt.PyJWTError):
        identify(monkeypatch, BAD[name]())


def test_jwks_failure_raises(monkeypatch):
    with pytest.raises(jwt.PyJWTError):
        identify(monkeypatch, id_token(), FakeJwks(fail=True))


def test_sends_the_pkce_verifier_and_our_client(monkeypatch):
    seen = {}

    def spy(req, timeout):
        seen["body"], seen["url"] = req.data.decode(), req.full_url
        return io.BytesIO(json.dumps({"id_token": id_token()}).encode())

    monkeypatch.setattr(citadel.urllib.request, "urlopen", spy)
    citadel.identify(settings(), FakeJwks(), "c0de", "ver1f1er", "https://api.example.test/oauth/callback")
    assert seen["url"] == "https://sso.example.test/oauth2/token"
    assert f"client_id={CLIENT_ID}" in seen["body"] and "code_verifier=ver1f1er" in seen["body"]
