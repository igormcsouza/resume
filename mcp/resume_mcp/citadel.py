"""Sign-in through Citadel: trade the login code for an ID token and return the verified user (`sub`)."""

import json
import urllib.request
from urllib.parse import urlencode

import jwt

from .settings import Settings


def identify(s: Settings, jwks, code: str, verifier: str, redirect_uri: str) -> str:
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": s.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()
    req = urllib.request.Request(
        f"{s.hosted_ui}/oauth2/token", body, {"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        id_token = json.load(r)["id_token"]
    claims = jwt.decode(
        id_token,
        jwks.get_signing_key_from_jwt(id_token).key,
        algorithms=["RS256"],  # never trust the header's alg
        issuer=s.issuer,
        audience=s.client_id,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    if claims.get("token_use") != "id":
        raise jwt.InvalidTokenError("not an ID token")
    return claims["sub"]
