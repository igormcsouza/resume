import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from resume_mcp.app import build_mcp
from resume_mcp.settings import Settings

ISSUER = "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_TEST"
CLIENT_ID = "test-client-id"
RESOURCE = "https://api.example.test/mcp"
HOSTED_UI = "https://resume-test.auth.sa-east-1.amazoncognito.com"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Mimics jwt.PyJWKClient: returns the key for any token, or raises like a failed JWKS fetch."""

    def __init__(self, key=KEY, fail=False):
        self.key, self.fail = key, fail

    def get_signing_key_from_jwt(self, token):
        if self.fail:
            raise jwt.PyJWKClientError("jwks unavailable")
        return SimpleNamespace(key=self.key.public_key())


def settings(as_mode="cognito") -> Settings:
    return Settings(issuer=ISSUER, client_id=CLIENT_ID, resource_url=RESOURCE, hosted_ui=HOSTED_UI, as_mode=as_mode)


def make_token(key=KEY, **over) -> str:
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "client_id": CLIENT_ID,
        "token_use": "access",
        "scope": "openid",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        **over,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


def alg_none_token() -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    claims = {"iss": ISSUER, "client_id": CLIENT_ID, "token_use": "access", "exp": int(time.time()) + 600}
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


def hs256_with_public_key_token() -> str:
    """Classic algorithm-confusion attack: sign with HS256 using the RSA public key bytes as the secret."""
    import hashlib
    import hmac

    from cryptography.hazmat.primitives import serialization

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    pub = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    claims = {"iss": ISSUER, "client_id": CLIENT_ID, "token_use": "access", "exp": int(time.time()) + 600}
    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(claims).encode())}"
    return f"{signing_input}.{b64(hmac.new(pub, signing_input.encode(), hashlib.sha256).digest())}"


HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method="tools/call", params=None, token=None):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return {"headers": headers, "content": json.dumps(body)}


BASE = "https://api.example.test"


@asynccontextmanager
async def running(server):
    """Serve a FastMCP app with its lifespan running (the session manager needs it)."""
    app = server.streamable_http_app()
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c


@pytest.fixture
def mcp_server():
    return build_mcp(settings(), jwks=FakeJwks())


@pytest.fixture
async def client(mcp_server):
    async with running(mcp_server) as c:
        yield c
