import time

import pytest

from resume_mcp.auth import CognitoVerifier

from .conftest import CLIENT_ID, OTHER_KEY, FakeJwks, alg_none_token, hs256_with_public_key_token, make_token, settings


def verifier(jwks=None):
    return CognitoVerifier(settings(), jwks or FakeJwks())


async def test_valid_access_token_is_accepted():
    got = await verifier().verify_token(make_token())
    assert got is not None
    assert got.client_id == CLIENT_ID
    assert got.expires_at > time.time()


BAD = {
    "garbage": lambda: "not-a-jwt",
    "empty": lambda: "",
    "expired": lambda: make_token(exp=int(time.time()) - 10),
    "no exp": lambda: make_token(exp=None),
    "wrong issuer": lambda: make_token(iss="https://evil.example/pool"),
    "wrong client_id": lambda: make_token(client_id="someone-else"),
    "missing client_id": lambda: make_token(client_id=None),
    "id token": lambda: make_token(token_use="id"),
    "no token_use": lambda: make_token(token_use=None),
    "signed by other key": lambda: make_token(key=OTHER_KEY),
    "alg none": alg_none_token,
    "hs256 confusion": hs256_with_public_key_token,
}


@pytest.mark.parametrize("name", BAD)
async def test_bad_tokens_are_rejected(name):
    assert await verifier().verify_token(BAD[name]()) is None


async def test_jwks_failure_rejects_instead_of_raising():
    assert await verifier(FakeJwks(fail=True)).verify_token(make_token()) is None
