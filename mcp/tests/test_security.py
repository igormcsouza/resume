"""Attack-shaped tests for the OAuth server: what a hostile caller, a stolen secret or a confused client must not achieve."""

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from resume_mcp.oauth import CODE, GRANT, PENDING, TOKEN, _sha

from .conftest import CLAUDE_CB, OWNER, bearer, pending_from

PING = {"name": "ping", "arguments": {}}


async def ping(client, token):
    from .conftest import rpc

    return await client.post("/mcp", **rpc(params=PING, token=token))


async def approved(flow, name="Claude"):
    """Owner approved: (client_id, authorization code, pending id)."""
    client_id = (await flow.register(name=name)).json()["client_id"]
    pending = pending_from(await flow.authorize(client_id))
    await flow.sign_in(pending)
    back = (await flow.decide(pending)).headers["location"]
    return client_id, parse_qs(urlsplit(back).query)["code"][0], pending


async def redeem(flow, client_id, code, redirect_uri=CLAUDE_CB, verifier=None):
    return await flow.token(
        grant_type="authorization_code", code=code, redirect_uri=redirect_uri, client_id=client_id,
        code_verifier=verifier or flow.verifier,
    )  # fmt: skip


def expire(table, pk):
    table.update_item(Key={"pk": pk, "sk": "META"}, UpdateExpression="SET expires_at = :e", ExpressionAttributeValues={":e": 1})


# -- secrets at rest ---------------------------------------------------------------------------------------------------
async def test_no_code_or_token_is_stored_in_plain_text(flow, table):
    client_id, code, _ = await approved(flow)
    tokens = (await redeem(flow, client_id, code)).json()
    stored = json.dumps(table.scan()["Items"], default=str)
    for secret in (code, tokens["access_token"], tokens["refresh_token"]):
        assert secret not in stored
    assert _sha(tokens["access_token"]) in stored  # only the digest is kept


# -- lifetime ----------------------------------------------------------------------------------------------------------
async def test_expired_authorization_code_is_refused(flow, table):
    client_id, code, _ = await approved(flow)
    expire(table, CODE + _sha(code))
    assert (await redeem(flow, client_id, code)).status_code == 400


async def test_expired_pending_request_cannot_sign_in_or_consent(flow, table):
    client_id = (await flow.register()).json()["client_id"]
    pending = pending_from(await flow.authorize(client_id))
    expire(table, PENDING + pending)
    assert (await flow.sign_in(pending)).status_code == 400
    assert (await flow.decide(pending)).status_code == 400


async def test_sign_in_cannot_be_replayed_to_swap_the_signed_in_user(flow, table):
    """Once a pending request has a subject, a second sign-in must not overwrite it."""
    client_id = (await flow.register()).json()["client_id"]
    pending = pending_from(await flow.authorize(client_id))
    assert (await flow.sign_in(pending)).status_code == 200
    assert (await flow.sign_in(pending)).status_code == 400
    assert table.get_item(Key={"pk": PENDING + pending, "sk": "META"})["Item"]["sub"] == OWNER


# -- registration and redirect handling --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "uri",
    [
        CLAUDE_CB + "/",
        CLAUDE_CB + "?x=1",
        CLAUDE_CB + "#frag",
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai.evil.example/api/mcp/auth_callback",
        "https://evil.example/https://claude.ai/api/mcp/auth_callback",
        "https://claude.ai@evil.example/api/mcp/auth_callback",
        "javascript:alert(1)",
        "http://localhost:3000/cb",
    ],
)
async def test_look_alike_redirect_uris_are_refused_at_registration(flow, uri):
    assert (await flow.register(uris=(uri,))).status_code == 400


async def test_a_good_uri_hidden_among_bad_ones_does_not_pass(flow):
    assert (await flow.register(uris=(CLAUDE_CB, "https://evil.example/cb"))).status_code == 400


async def test_too_many_redirect_uris_are_refused(flow):
    assert (await flow.register(uris=tuple([CLAUDE_CB] * 6))).status_code == 400


async def test_client_name_is_capped(flow):
    cid = (await flow.register(name="N" * 5000)).json()["client_id"]
    pending = pending_from(await flow.authorize(cid))
    page = await flow.sign_in(pending)
    assert "N" * 101 not in page.text


async def test_authorize_for_an_unknown_client_never_redirects(flow):
    r = await flow.authorize("no-such-client")
    assert r.status_code == 400 and "location" not in r.headers


async def test_state_cannot_inject_parameters_into_the_redirect(flow):
    client_id = (await flow.register()).json()["client_id"]
    nasty = "a&code=evil&error=x#y"
    pending = pending_from(await flow.authorize(client_id, state=nasty))
    await flow.sign_in(pending)
    back = urlsplit((await flow.decide(pending)).headers["location"])
    q = parse_qs(back.query)
    assert q["state"] == [nasty] and len(q["code"]) == 1 and q["code"][0] != "evil" and "error" not in q


# -- PKCE and scope ----------------------------------------------------------------------------------------------------
async def test_plain_pkce_method_is_refused(flow):
    client_id = (await flow.register()).json()["client_id"]
    r = await flow.c.get(
        "/authorize",
        params={
            "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB, "state": "s",
            "code_challenge": "x" * 43, "code_challenge_method": "plain",
        },
    )  # fmt: skip
    assert "code" not in parse_qs(urlsplit(r.headers.get("location", "")).query)
    assert r.status_code in (302, 400) and "citadel" not in r.headers.get("location", "") and "oauth2/authorize" not in r.headers.get("location", "")


async def test_missing_pkce_challenge_is_refused(flow):
    client_id = (await flow.register()).json()["client_id"]
    r = await flow.c.get(
        "/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB, "state": "s"}
    )
    assert "oauth2/authorize" not in r.headers.get("location", "")


async def test_unknown_scope_is_refused_at_authorize(flow):
    client_id = (await flow.register()).json()["client_id"]
    r = await flow.c.get(
        "/authorize",
        params={
            "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB, "state": "s", "scope": "admin",
            "code_challenge": flow.challenge, "code_challenge_method": "S256",
        },
    )  # fmt: skip
    assert "oauth2/authorize" not in r.headers.get("location", "")


async def test_refresh_cannot_widen_the_scope(flow):
    client_id, tokens = await flow.connect()
    r = await flow.token(grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id, scope="admin")
    assert r.status_code == 400


async def test_code_redemption_needs_the_same_redirect_uri(flow):
    client_id, code, _ = await approved(flow)
    assert (await redeem(flow, client_id, code, redirect_uri="https://claude.com/api/mcp/auth_callback")).status_code == 400


# -- tokens ------------------------------------------------------------------------------------------------------------
async def test_refresh_and_access_tokens_are_not_interchangeable(flow):
    client_id, tokens = await flow.connect()
    assert (await ping(flow.c, tokens["refresh_token"])).status_code == 401
    r = await flow.token(grant_type="refresh_token", refresh_token=tokens["access_token"], client_id=client_id)
    assert r.status_code == 400


async def test_an_authorization_code_is_not_a_bearer_token(flow):
    _, code, _ = await approved(flow)
    assert (await ping(flow.c, code)).status_code == 401


async def test_refresh_after_disconnect_fails(flow):
    client_id, tokens = await flow.connect()
    rows = (await flow.c.get("/connections", headers=bearer(tokens["access_token"]))).json()["connections"]
    await flow.c.delete(f"/connections/{rows[0]['id']}", headers=bearer(tokens["access_token"]))
    r = await flow.token(grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
    assert r.status_code == 400 and (await ping(flow.c, tokens["access_token"])).status_code == 401


async def test_refusals_all_look_the_same(flow):
    """An unknown code, a wrong verifier and a wrong client must not tell the caller which part was wrong."""
    client_id, code, _ = await approved(flow)
    other = (await flow.register(name="Other")).json()["client_id"]
    unknown = (await redeem(flow, client_id, "nope")).json()
    wrong_client = (await redeem(flow, other, code)).json()
    assert unknown["error"] == "invalid_grant" and wrong_client["error"] == "invalid_grant"
    assert unknown["error_description"] == wrong_client["error_description"]


async def test_parallel_redemption_of_one_code_yields_one_token_set(flow):
    client_id, code, _ = await approved(flow)
    a, b = await asyncio.gather(redeem(flow, client_id, code), redeem(flow, client_id, code))
    assert sorted([a.status_code, b.status_code]) == [200, 400]


async def test_parallel_refresh_of_one_token_yields_one_token_set(flow):
    client_id, tokens = await flow.connect()
    refresh = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    a, b = await asyncio.gather(flow.token(**refresh), flow.token(**refresh))
    assert sorted([a.status_code, b.status_code]) == [200, 400]


# -- consent -----------------------------------------------------------------------------------------------------------
async def test_consent_is_post_only(flow):
    assert (await flow.c.get("/oauth/consent", params={"state": "x", "decision": "approve"})).status_code in (404, 405)


async def test_consent_without_an_explicit_approve_gives_no_code(flow):
    client_id = (await flow.register()).json()["client_id"]
    pending = pending_from(await flow.authorize(client_id))
    await flow.sign_in(pending)
    r = await flow.decide(pending, "maybe")
    assert "code" not in parse_qs(urlsplit(r.headers.get("location", "")).query)


async def test_consent_for_someone_elses_pending_request_gives_nothing(flow):
    """A guessed or foreign pending id that was never signed in cannot be approved."""
    client_id = (await flow.register()).json()["client_id"]
    pending_from(await flow.authorize(client_id))
    assert (await flow.decide("guess" * 10)).status_code == 400


# -- tenancy -----------------------------------------------------------------------------------------------------------
async def test_another_owners_grants_are_invisible_and_cannot_be_revoked(flow, table):
    _, tokens = await flow.connect("Mine")
    table.put_item(
        Item={"pk": GRANT + "other-sub", "sk": "g1", "client_id": "c", "client_name": "Theirs", "created_at": 1,
              "revoked": False, "expires_at": 9999999999, "ttl": 9999999999}
    )  # fmt: skip
    rows = (await flow.c.get("/connections", headers=bearer(tokens["access_token"]))).json()["connections"]
    assert [r["name"] for r in rows] == ["Mine"]
    await flow.c.delete("/connections/g1", headers=bearer(tokens["access_token"]))
    assert table.get_item(Key={"pk": GRANT + "other-sub", "sk": "g1"})["Item"]["revoked"] is False


async def test_a_token_belongs_to_the_approving_subject_only(flow, table):
    _, tokens = await flow.connect()
    item = table.get_item(Key={"pk": TOKEN + _sha(tokens["access_token"]), "sk": "META"})["Item"]
    assert item["sub"] == OWNER
