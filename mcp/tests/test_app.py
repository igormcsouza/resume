import json

import pytest

from resume_mcp.app import build_mcp

from .conftest import (
    HOSTED_UI,
    ISSUER,
    RESOURCE,
    FakeJwks,
    alg_none_token,
    make_token,
    rpc,
    running,
    settings,
)

PING = {"name": "ping", "arguments": {}}


async def test_no_token_gets_401_with_resource_metadata_hint(client):
    r = await client.post("/mcp", **rpc(params=PING))
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]


@pytest.mark.parametrize("token", ["garbage", alg_none_token()])
async def test_bad_token_gets_401(client, token):
    r = await client.post("/mcp", **rpc(params=PING, token=token))
    assert r.status_code == 401


async def test_jwks_outage_is_401_not_500():
    async with running(build_mcp(settings(), jwks=FakeJwks(fail=True))) as c:
        r = await c.post("/mcp", **rpc(params=PING, token=make_token()))
    assert r.status_code == 401


async def test_valid_token_can_call_ping(client):
    r = await client.post("/mcp", **rpc(params=PING, token=make_token()))
    assert r.status_code == 200
    assert "pong" in r.text


async def test_every_registered_tool_requires_auth(mcp_server, client):
    tools = await mcp_server.list_tools()
    assert tools, "server must register at least one tool"
    for tool in tools:
        r = await client.post("/mcp", **rpc(params={"name": tool.name, "arguments": {}}))
        assert r.status_code == 401, tool.name


async def test_protected_resource_metadata_points_at_cognito(client):
    r = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].rstrip("/") == RESOURCE
    assert [a.rstrip("/") for a in body["authorization_servers"]] == [ISSUER]


async def test_shim_mode_points_at_our_own_origin():
    async with running(build_mcp(settings(as_mode="shim"), jwks=FakeJwks())) as c:
        body = (await c.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert [a.rstrip("/") for a in body["authorization_servers"]] == ["https://api.example.test"]


async def test_authorization_server_metadata_shim_fronts_cognito(client):
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["authorization_endpoint"] == f"{HOSTED_UI}/oauth2/authorize"
    assert body["token_endpoint"] == f"{HOSTED_UI}/oauth2/token"
    assert body["jwks_uri"] == f"{ISSUER}/.well-known/jwks.json"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "code" in body["response_types_supported"]


def _event(path, domain="abc123.execute-api.sa-east-1.amazonaws.com"):
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": domain, "accept": "application/json"},
        "requestContext": {"domainName": domain, "http": {"method": "GET", "path": path, "sourceIp": "1.2.3.4"}},
        "isBase64Encoded": False,
    }


def test_handler_derives_resource_url_from_the_request_domain(monkeypatch):
    """The API URL is unknown when the Lambda is configured, so RESOURCE_URL is optional and read from the event."""
    monkeypatch.setenv("ISSUER", ISSUER)
    monkeypatch.setenv("CLIENT_ID", "x")
    monkeypatch.setenv("HOSTED_UI", HOSTED_UI)
    monkeypatch.delenv("RESOURCE_URL", raising=False)
    from resume_mcp import handler

    res = handler.handler(_event("/.well-known/oauth-protected-resource/mcp"), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["resource"].rstrip("/") == "https://abc123.execute-api.sa-east-1.amazonaws.com/mcp"


def test_handler_serves_the_authorization_server_shim(monkeypatch):
    monkeypatch.setenv("ISSUER", ISSUER)
    monkeypatch.setenv("CLIENT_ID", "x")
    monkeypatch.setenv("HOSTED_UI", HOSTED_UI)
    from resume_mcp import handler

    res = handler.handler(_event("/.well-known/oauth-authorization-server"), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["token_endpoint"] == f"{HOSTED_UI}/oauth2/token"
