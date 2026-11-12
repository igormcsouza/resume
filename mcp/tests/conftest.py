import base64
import hashlib
import json
import re
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import boto3
import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from moto import mock_aws

from resume_mcp import citadel
from resume_mcp.app import build_mcp
from resume_mcp.oauth import Oauth
from resume_mcp.settings import Settings

ISSUER = "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_TEST"
CLIENT_ID = "citadel-client-id"
HOSTED_UI = "https://sso.example.test"
BASE = "https://api.example.test"
RESOURCE = f"{BASE}/mcp"
OWNER = "owner-sub"
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"

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


def settings() -> Settings:
    return Settings(
        issuer=ISSUER, client_id=CLIENT_ID, hosted_ui=HOSTED_UI, owner_subs=frozenset({OWNER}), resource_url=RESOURCE
    )


def id_token(key=KEY, **over) -> str:
    claims = {
        "iss": ISSUER, "sub": OWNER, "aud": CLIENT_ID, "token_use": "id",
        "iat": int(time.time()), "exp": int(time.time()) + 600, **over,
    }  # fmt: skip
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": "k1"})


def alg_none_token() -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    claims = {"iss": ISSUER, "sub": OWNER, "aud": CLIENT_ID, "token_use": "id", "exp": int(time.time()) + 600}
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method="tools/call", params=None, token=None):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return {"headers": headers, "content": json.dumps(body)}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def running(server):
    """Serve a FastMCP app with its lifespan running (the session manager needs it)."""
    app = server.streamable_http_app()
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c


def new_table():
    return boto3.resource("dynamodb", region_name="sa-east-1").create_table(
        TableName="resume",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def table():
    with mock_aws():
        yield new_table()


@pytest.fixture
def oauth(table):
    return Oauth(table, BASE, HOSTED_UI, CLIENT_ID)


@pytest.fixture
def mcp_server(oauth):
    return build_mcp(settings(), oauth, jwks=FakeJwks())


@pytest.fixture
async def client(mcp_server):
    async with running(mcp_server) as c:
        yield c


class Flow:
    """Drives what Claude and the owner do: register, authorize, sign in through Citadel, approve, redeem the code."""

    def __init__(self, client, monkeypatch):
        self.c, self.mp = client, monkeypatch
        self.verifier = "v" * 64
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()

    async def register(self, name="Claude", uris=(CLAUDE_CB,)):
        r = await self.c.post(
            "/register",
            json={
                "client_name": name, "redirect_uris": list(uris), "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            },
        )  # fmt: skip
        return r

    async def authorize(self, client_id, redirect_uri=CLAUDE_CB, state="st8"):
        return await self.c.get(
            "/authorize",
            params={
                "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
                "code_challenge": self.challenge, "code_challenge_method": "S256",
            },
        )  # fmt: skip

    async def sign_in(self, pending_id, sub=OWNER):
        self.mp.setattr(citadel, "identify", lambda *a: sub)
        return await self.c.get("/oauth/callback", params={"state": pending_id, "code": "citadel-code"})

    async def decide(self, pending_id, decision="approve"):
        return await self.c.post("/oauth/consent", data={"state": pending_id, "decision": decision})

    async def token(self, **form):
        return await self.c.post("/token", data=form)

    async def connect(self, name="Claude"):
        """Whole happy path. Returns (client_id, token response json)."""
        client_id = (await self.register(name)).json()["client_id"]
        loc = (await self.authorize(client_id)).headers["location"]
        pending = parse_qs(urlsplit(loc).query)["state"][0]
        assert (await self.sign_in(pending)).status_code == 200
        back = (await self.decide(pending)).headers["location"]
        code = parse_qs(urlsplit(back).query)["code"][0]
        r = await self.token(
            grant_type="authorization_code", code=code, redirect_uri=CLAUDE_CB, client_id=client_id,
            code_verifier=self.verifier,
        )  # fmt: skip
        assert r.status_code == 200, r.text
        return client_id, r.json()


@pytest.fixture
def flow(client, monkeypatch):
    return Flow(client, monkeypatch)


def pending_from(response) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def csrf_free_form_state(html: str) -> str:
    return re.search(r"name=state value='([^']+)'", html).group(1)
