import json
import time
from urllib.parse import parse_qs, urlsplit

from resume_mcp import handler
from resume_mcp.oauth import MAX_REGISTRATIONS_PER_HOUR

from .conftest import (
    BASE,
    CLAUDE_CB,
    HOSTED_UI,
    ISSUER,
    OWNER,
    RESOURCE,
    bearer,
    csrf_free_form_state,
    pending_from,
    rpc,
)

PING = {"name": "ping", "arguments": {}}


async def call_ping(client, token):
    return await client.post("/mcp", **rpc(params=PING, token=token))


# -- discovery -----------------------------------------------------------------------------------------------------------
async def test_no_token_gets_401_with_resource_metadata_hint(client):
    r = await call_ping(client, None)
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]


async def test_protected_resource_points_at_our_own_origin(client):
    body = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert body["resource"].rstrip("/") == RESOURCE
    assert [a.rstrip("/") for a in body["authorization_servers"]] == [BASE]


async def test_authorization_server_metadata_is_ours_and_public_pkce_only(client):
    body = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert body["authorization_endpoint"] == f"{BASE}/authorize"
    assert body["token_endpoint"] == f"{BASE}/token"
    assert body["registration_endpoint"] == f"{BASE}/register"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]


# -- registration and authorize ------------------------------------------------------------------------------------------
async def test_registration_refuses_foreign_redirect_uris(flow):
    r = await flow.register(uris=("https://evil.example/cb",))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


async def test_registration_refuses_secret_based_clients(flow):
    r = await flow.c.post("/register", json={"client_name": "x", "redirect_uris": [CLAUDE_CB]})
    assert r.status_code == 400


async def test_registration_is_rate_limited(flow):
    for _ in range(MAX_REGISTRATIONS_PER_HOUR):
        assert (await flow.register()).status_code == 201
    assert (await flow.register()).status_code == 400


async def test_authorize_with_unregistered_redirect_never_redirects(flow):
    client_id = (await flow.register()).json()["client_id"]
    r = await flow.authorize(client_id, redirect_uri="https://evil.example/cb")
    assert r.status_code == 400 and "location" not in r.headers


async def test_authorize_sends_the_browser_to_citadel_with_our_own_pkce(flow):
    client_id = (await flow.register()).json()["client_id"]
    r = await flow.authorize(client_id)
    assert r.status_code == 302
    u = urlsplit(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert f"{u.scheme}://{u.netloc}{u.path}" == f"{HOSTED_UI}/oauth2/authorize"
    assert q["redirect_uri"] == f"{BASE}/oauth/callback" and q["code_challenge_method"] == "S256"
    assert q["client_id"] != client_id  # Citadel's client for this app, not Claude's registration


# -- sign-in and consent -------------------------------------------------------------------------------------------------
async def start(flow):
    client_id = (await flow.register(name="My <b>Claude</b>")).json()["client_id"]
    return client_id, pending_from(await flow.authorize(client_id))


async def test_consent_page_names_the_client_and_escapes_it(flow):
    _, pending = await start(flow)
    r = await flow.sign_in(pending)
    assert r.status_code == 200
    assert "My &lt;b&gt;Claude&lt;/b&gt;" in r.text and "<b>Claude</b>" not in r.text
    assert csrf_free_form_state(r.text) == pending
    assert r.headers["cache-control"] == "no-store" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


async def test_someone_else_signing_in_is_refused_and_cannot_consent(flow):
    _, pending = await start(flow)
    assert (await flow.sign_in(pending, sub="intruder")).status_code == 403
    assert (await flow.decide(pending)).status_code == 400  # never signed in as the owner: no code


async def test_consent_needs_the_owner_to_have_signed_in_first(flow):
    _, pending = await start(flow)
    assert (await flow.decide(pending)).status_code == 400


async def test_failed_citadel_exchange_is_a_generic_400(flow, monkeypatch):
    from resume_mcp import citadel

    _, pending = await start(flow)

    def boom(*a):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(citadel, "identify", boom)
    r = await flow.c.get("/oauth/callback", params={"state": pending, "code": "x"})
    assert r.status_code == 400 and "secret detail" not in r.text


async def test_callback_with_unknown_state_is_400(flow):
    assert (await flow.c.get("/oauth/callback", params={"state": "nope", "code": "x"})).status_code == 400


async def test_deny_redirects_with_access_denied_and_state(flow):
    _, pending = await start(flow)
    await flow.sign_in(pending)
    r = await flow.decide(pending, "deny")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.headers["location"].startswith(CLAUDE_CB) and q["error"] == ["access_denied"] and q["state"] == ["st8"]


async def test_a_pending_request_can_be_answered_once(flow):
    _, pending = await start(flow)
    await flow.sign_in(pending)
    assert (await flow.decide(pending)).status_code == 303
    assert (await flow.decide(pending)).status_code == 400


# -- tokens --------------------------------------------------------------------------------------------------------------
async def test_full_flow_gives_a_token_that_reaches_the_tools(flow):
    _, tokens = await flow.connect()
    assert tokens["token_type"].lower() == "bearer" and tokens["refresh_token"]
    r = await call_ping(flow.c, tokens["access_token"])
    assert r.status_code == 200 and "pong" in r.text


async def test_garbage_token_is_401(flow):
    assert (await call_ping(flow.c, "garbage")).status_code == 401


async def redeem(flow, client_id, code, verifier=None):
    return await flow.token(
        grant_type="authorization_code", code=code, redirect_uri=CLAUDE_CB, client_id=client_id,
        code_verifier=verifier or flow.verifier,
    )  # fmt: skip


async def approved_code(flow):
    client_id, pending = await start(flow)
    await flow.sign_in(pending)
    back = (await flow.decide(pending)).headers["location"]
    return client_id, parse_qs(urlsplit(back).query)["code"][0]


async def test_wrong_pkce_verifier_is_refused(flow):
    client_id, code = await approved_code(flow)
    assert (await redeem(flow, client_id, code, verifier="x" * 64)).status_code == 400


async def test_code_belongs_to_the_client_that_asked(flow):
    _, code = await approved_code(flow)
    other = (await flow.register(name="Other")).json()["client_id"]
    assert (await redeem(flow, other, code)).status_code == 400


async def test_replayed_code_revokes_the_grant(flow):
    client_id, code = await approved_code(flow)
    first = await redeem(flow, client_id, code)
    assert first.status_code == 200
    assert (await redeem(flow, client_id, code)).status_code == 400
    assert (await call_ping(flow.c, first.json()["access_token"])).status_code == 401


async def refresh(flow, client_id, token):
    return await flow.token(grant_type="refresh_token", refresh_token=token, client_id=client_id)


async def test_refresh_rotates_and_reuse_revokes_the_grant(flow):
    client_id, tokens = await flow.connect()
    new = await refresh(flow, client_id, tokens["refresh_token"])
    assert new.status_code == 200 and new.json()["refresh_token"] != tokens["refresh_token"]
    assert (await call_ping(flow.c, new.json()["access_token"])).status_code == 200
    assert (await refresh(flow, client_id, tokens["refresh_token"])).status_code == 400  # the old one came back
    assert (await call_ping(flow.c, new.json()["access_token"])).status_code == 401  # so the grant is dead


async def test_refresh_token_is_bound_to_its_client(flow):
    _, tokens = await flow.connect()
    other = (await flow.register(name="Other")).json()["client_id"]
    assert (await refresh(flow, other, tokens["refresh_token"])).status_code == 400


async def test_expired_access_token_is_401(flow, oauth, table):
    _, tokens = await flow.connect()
    from resume_mcp.oauth import TOKEN, _sha

    table.update_item(
        Key={"pk": TOKEN + _sha(tokens["access_token"]), "sk": "META"},
        UpdateExpression="SET expires_at = :e",
        ExpressionAttributeValues={":e": int(time.time()) - 1},
    )
    assert (await call_ping(flow.c, tokens["access_token"])).status_code == 401


# -- connections endpoint ------------------------------------------------------------------------------------------------
async def test_connections_need_a_token(client):
    assert (await client.get("/connections")).status_code == 401
    assert (await client.get("/connections", headers=bearer("garbage"))).status_code == 401
    assert (await client.delete("/connections/abc")).status_code == 401


async def test_connections_list_each_grant_and_flag_the_caller(flow):
    await flow.connect("Phone")
    _, second = await flow.connect("Laptop")
    rows = (await flow.c.get("/connections", headers=bearer(second["access_token"]))).json()["connections"]
    assert [r["name"] for r in rows] == ["Laptop", "Phone"] or {r["name"] for r in rows} == {"Laptop", "Phone"}
    assert {r["name"]: r["current"] for r in rows} == {"Laptop": True, "Phone": False}
    assert all(set(r) == {"id", "name", "created_at", "expires_at", "current"} for r in rows)
    assert "token" not in json.dumps(rows)


async def test_disconnect_revokes_one_grant_only(flow):
    _, phone = await flow.connect("Phone")
    _, laptop = await flow.connect("Laptop")
    rows = (await flow.c.get("/connections", headers=bearer(laptop["access_token"]))).json()["connections"]
    phone_id = next(r["id"] for r in rows if r["name"] == "Phone")
    assert (await flow.c.delete(f"/connections/{phone_id}", headers=bearer(laptop["access_token"]))).status_code == 204
    assert (await call_ping(flow.c, phone["access_token"])).status_code == 401
    assert (await call_ping(flow.c, laptop["access_token"])).status_code == 200
    rows = (await flow.c.get("/connections", headers=bearer(laptop["access_token"]))).json()["connections"]
    assert [r["name"] for r in rows] == ["Laptop"]


async def test_disconnect_of_an_unknown_grant_creates_nothing(flow, table):
    _, tokens = await flow.connect()
    before = table.scan()["Count"]
    assert (await flow.c.delete("/connections/nope", headers=bearer(tokens["access_token"]))).status_code == 204
    assert table.scan()["Count"] == before


# -- Lambda entry point --------------------------------------------------------------------------------------------------
def _event(path, domain="abc123.execute-api.sa-east-1.amazonaws.com"):
    return {
        "version": "2.0", "rawPath": path, "rawQueryString": "",
        "headers": {"host": domain, "accept": "application/json"},
        "requestContext": {"domainName": domain, "http": {"method": "GET", "path": path, "sourceIp": "1.2.3.4"}},
        "isBase64Encoded": False,
    }  # fmt: skip


def test_handler_derives_resource_url_from_the_request_domain(table, monkeypatch):
    """The API URL is unknown when the Lambda is configured, so RESOURCE_URL is optional and read from the event."""
    for k, v in {"ISSUER": ISSUER, "CLIENT_ID": "c", "HOSTED_UI": HOSTED_UI, "OWNER_SUBS": OWNER, "TABLE_NAME": "resume"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    monkeypatch.delenv("RESOURCE_URL", raising=False)
    res = handler.handler(_event("/.well-known/oauth-protected-resource/mcp"), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["resource"].rstrip("/") == "https://abc123.execute-api.sa-east-1.amazonaws.com/mcp"
    res = handler.handler(_event("/.well-known/oauth-authorization-server"), None)
    assert json.loads(res["body"])["token_endpoint"] == "https://abc123.execute-api.sa-east-1.amazonaws.com/token"


def test_handler_uses_the_public_url_when_a_cdn_fronts_the_api(table, monkeypatch):
    """Behind CloudFront the request Host is the API's, so PUBLIC_URL says what clients should see."""
    for k, v in {
        "ISSUER": ISSUER, "CLIENT_ID": "c", "HOSTED_UI": HOSTED_UI, "OWNER_SUBS": OWNER, "TABLE_NAME": "resume",
        "PUBLIC_URL": "https://resume.example.test/",
    }.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    res = handler.handler(_event("/.well-known/oauth-authorization-server"), None)
    body = json.loads(res["body"])
    assert body["issuer"].rstrip("/") == "https://resume.example.test"
    assert body["authorization_endpoint"] == "https://resume.example.test/authorize"
    assert handler.build_oauth(handler.dataclasses.replace(handler.Settings.from_env(), resource_url="https://resume.example.test/mcp")).callback_url == "https://resume.example.test/oauth/callback"
