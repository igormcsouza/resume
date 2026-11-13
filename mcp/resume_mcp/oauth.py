"""OAuth 2.1 authorization server for the Resume MCP (Claude connectors), as a provider for the MCP SDK.

A connector needs only the MCP URL: Claude registers itself (RFC 7591), the owner signs in through Citadel and approves
on a one-screen consent page, then Claude trades a PKCE code for tokens. Each approval is a *grant* (revocable alone).
The SDK serves /register, /authorize, /token, /revoke and the discovery documents; this class is the storage and the
rules behind them. The sign-in step lives in `app.py` (/oauth/callback, /oauth/consent).

Only SHA-256 digests of codes and tokens are stored. Single-use things (codes, refresh tokens) are consumed with a
conditional write; reusing one is treated as theft and revokes the whole grant.
"""

import base64
import contextlib
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SCOPE = "resume:mcp"
ALLOWED_REDIRECTS = frozenset({"https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"})
PENDING_TTL, CODE_TTL, ACCESS_TTL, REFRESH_TTL, CODE_KEEP = 600, 60, 3600, 90 * 86400, 86400
CLIENT_TTL = REFRESH_TTL + 30 * 86400  # a client record must outlive the grants made with it
MAX_REGISTRATIONS_PER_HOUR = 30  # registration is public: bound what an anonymous caller can write
MAX_REDIRECT_URIS, MAX_CLIENT_NAME = 5, 100

CLIENT, RATE, PENDING, CODE, TOKEN, GRANT = "MCPCLIENT#", "MCPRATE#", "MCPPEND#", "MCPCODE#", "MCPTOKEN#", "MCPGRANT#"


def now() -> int:
    return int(time.time())


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _secret() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _invalid_grant() -> TokenError:
    # One fixed text for every cause, so a response reveals nothing about why a grant was refused.
    return TokenError("invalid_grant", "The authorization grant is invalid, expired or revoked.")


class Oauth:
    def __init__(self, table: Any, base_url: str, hosted_ui: str, citadel_client_id: str):
        self._t, self._c = table, table.meta.client  # the resource-level client takes plain Python values
        self.callback_url = f"{base_url}/oauth/callback"
        self._hosted_ui, self._citadel_client = hosted_ui, citadel_client_id

    # -- storage helpers -----------------------------------------------------------------------------------------------
    def _get(self, pk: str, sk: str = "META") -> dict[str, Any] | None:
        return self._t.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")

    def _put(self, pk: str, sk: str = "META", **attrs: Any) -> None:
        self._t.put_item(Item={"pk": pk, "sk": sk, **attrs})

    def _consume(self, pk: str) -> bool:
        """Single use: True for the first caller while unexpired, False for everyone after."""
        try:
            self._t.update_item(
                Key={"pk": pk, "sk": "META"},
                UpdateExpression="SET used = :t",
                ConditionExpression="used = :f AND expires_at > :now",
                ExpressionAttributeValues={":t": True, ":f": False, ":now": now()},
            )
        except self._c.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def _revoke(self, sub: str, grant_id: str) -> None:
        with contextlib.suppress(self._c.exceptions.ConditionalCheckFailedException):
            self._t.update_item(
                Key={"pk": GRANT + sub, "sk": grant_id},
                UpdateExpression="SET revoked = :t",
                ConditionExpression="attribute_exists(pk)",  # unknown grant: no-op, never create a stub
                ExpressionAttributeValues={":t": True},
            )

    def _grant_live(self, sub: str, grant_id: str) -> dict[str, Any] | None:
        grant = self._get(GRANT + sub, grant_id)
        return None if grant is None or grant["revoked"] else grant

    # -- clients (RFC 7591) --------------------------------------------------------------------------------------------
    async def register_client(self, info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in info.redirect_uris or []]
        if not uris or len(uris) > MAX_REDIRECT_URIS or any(u not in ALLOWED_REDIRECTS for u in uris):  # exact match
            raise RegistrationError("invalid_redirect_uri", "redirect_uri is not allowed for this server.")
        if info.token_endpoint_auth_method != "none":  # public PKCE clients only: no secret is ever stored
            raise RegistrationError("invalid_client_metadata", "Only token_endpoint_auth_method none is supported.")
        hour = now() // 3600
        try:
            self._t.update_item(
                Key={"pk": RATE + str(hour), "sk": "META"},
                UpdateExpression="ADD cnt :one SET #ttl = :ttl",
                ConditionExpression="attribute_not_exists(cnt) OR cnt < :max",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={":one": 1, ":max": MAX_REGISTRATIONS_PER_HOUR, ":ttl": (hour + 2) * 3600},
            )
        except self._c.exceptions.ConditionalCheckFailedException:
            raise RegistrationError("invalid_client_metadata", "Registration is temporarily unavailable.") from None
        info.client_name = (info.client_name or "MCP client")[:MAX_CLIENT_NAME]
        self._put(
            CLIENT + str(info.client_id),
            client=info.model_dump_json(),
            expires_at=now() + CLIENT_TTL,
            ttl=now() + CLIENT_TTL,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        item = self._get(CLIENT + client_id)
        if item is None or item["expires_at"] <= now():
            return None
        return OAuthClientInformationFull.model_validate_json(item["client"])

    # -- authorize -> Citadel sign-in -> consent -> code ---------------------------------------------------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        scopes = params.scopes or [SCOPE]
        if set(scopes) != {SCOPE}:
            raise AuthorizeError("invalid_scope", f"Only the scope {SCOPE} is supported.")
        pending_id, verifier = _secret(), _secret()  # verifier: our own PKCE secret for the Citadel leg
        self._put(
            PENDING + pending_id,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            explicit=params.redirect_uri_provided_explicitly,
            challenge=params.code_challenge,
            state=params.state or "",
            scopes=scopes,
            verifier=verifier,
            sub="",  # set once Citadel has signed the owner in
            used=False,
            expires_at=now() + PENDING_TTL,
            ttl=now() + PENDING_TTL,
        )
        return f"{self._hosted_ui}/oauth2/authorize?" + urlencode(
            {
                "client_id": self._citadel_client,
                "response_type": "code",
                "scope": "openid",
                "redirect_uri": self.callback_url,
                "state": pending_id,
                "code_challenge": _s256(verifier),
                "code_challenge_method": "S256",
            }
        )

    def pending(self, pending_id: str) -> dict[str, Any] | None:
        item = self._get(PENDING + pending_id) if pending_id else None
        return None if item is None or item["used"] or item["expires_at"] <= now() else item

    def signed_in(self, pending_id: str, sub: str) -> bool:
        """Citadel vouched for `sub`: from here the consent screen may be answered. False if already signed in."""
        try:
            self._t.update_item(
                Key={"pk": PENDING + pending_id, "sk": "META"},
                UpdateExpression="SET #sub = :s",
                ConditionExpression="#sub = :empty AND used = :f",
                ExpressionAttributeNames={"#sub": "sub"},  # `sub` is a DynamoDB reserved word
                ExpressionAttributeValues={":s": sub, ":empty": "", ":f": False},
            )
        except self._c.exceptions.ConditionalCheckFailedException:
            return False  # a second sign-in never replaces the first subject
        return True

    def decide(self, pending_id: str, approve: bool) -> str | None:
        """The signed-in owner answers. Returns the URL to send the browser to, or None if the request is not valid."""
        item = self.pending(pending_id)
        if item is None or not item["sub"] or not self._consume(PENDING + pending_id):
            return None
        if not approve:
            return construct_redirect_uri(item["redirect_uri"], error="access_denied", state=item["state"] or None)
        code = _secret()
        self._put(
            CODE + _sha(code),
            sub=item["sub"],
            grant_id=_secret(),
            client_id=item["client_id"],
            redirect_uri=item["redirect_uri"],
            explicit=item["explicit"],
            challenge=item["challenge"],
            scopes=item["scopes"],
            used=False,
            expires_at=now() + CODE_TTL,
            ttl=now() + CODE_KEEP,  # used codes linger so a replay can be recognised
        )
        return construct_redirect_uri(item["redirect_uri"], code=code, state=item["state"] or None)

    # -- tokens --------------------------------------------------------------------------------------------------------
    async def load_authorization_code(self, client: OAuthClientInformationFull, code: str) -> AuthorizationCode | None:
        item = self._get(CODE + _sha(code))
        if item is None or item["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=code,
            scopes=item["scopes"],
            expires_at=int(item["expires_at"]),
            client_id=item["client_id"],
            code_challenge=item["challenge"],
            redirect_uri=item["redirect_uri"],
            redirect_uri_provided_explicitly=item["explicit"],
            subject=item["sub"],
        )

    def _issue(self, sub: str, grant_id: str, client: OAuthClientInformationFull, scopes: list[str], grant: dict) -> OAuthToken:
        access, refresh = _secret(), _secret()

        def token(kind: str, secret: str, life: int) -> dict[str, Any]:
            return {
                "pk": TOKEN + _sha(secret), "sk": "META", "kind": kind, "sub": sub, "grant_id": grant_id,
                "client_id": client.client_id, "scopes": scopes, "used": False,
                "expires_at": now() + life, "ttl": now() + life,
            }  # fmt: skip

        grant = {**grant, "expires_at": now() + REFRESH_TTL, "ttl": now() + REFRESH_TTL}
        items = [token("access", access, ACCESS_TTL), token("refresh", refresh, REFRESH_TTL), grant]
        self._c.transact_write_items(TransactItems=[{"Put": {"TableName": self._t.name, "Item": i}} for i in items])
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes), refresh_token=refresh)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, code: AuthorizationCode) -> OAuthToken:
        pk = CODE + _sha(code.code)
        item = self._get(pk)
        if item is None:
            raise _invalid_grant()
        sub, grant_id = item["sub"], item["grant_id"]
        if not self._consume(pk):  # already used (or expired): a replay, so assume the code leaked
            self._revoke(sub, grant_id)
            raise _invalid_grant()
        grant = {
            "pk": GRANT + sub, "sk": grant_id, "client_id": client.client_id, "client_name": client.client_name,
            "created_at": now(), "revoked": False,
        }  # fmt: skip
        return self._issue(sub, grant_id, client, item["scopes"], grant)

    def _token(self, token: str, kind: str, client_id: str | None = None) -> dict[str, Any] | None:
        item = self._get(TOKEN + _sha(token))
        if item is None or item["kind"] != kind or (client_id and item["client_id"] != client_id):
            return None
        return item

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        item = self._token(refresh_token, "refresh", client.client_id)
        if item is None or self._grant_live(item["sub"], item["grant_id"]) is None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=item["client_id"],
            scopes=item["scopes"],
            expires_at=int(item["expires_at"]),
            subject=item["sub"],
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        item = self._token(refresh_token.token, "refresh", client.client_id)
        grant = item and self._grant_live(item["sub"], item["grant_id"])
        if item is None or grant is None:
            raise _invalid_grant()
        if set(scopes) - set(item["scopes"]):
            raise TokenError("invalid_scope", "Scope was not granted.")
        if not self._consume(TOKEN + _sha(refresh_token.token)):
            self._revoke(item["sub"], item["grant_id"])  # a rotated or expired refresh token came back: assume it leaked
            raise _invalid_grant()
        return self._issue(item["sub"], item["grant_id"], client, scopes or item["scopes"], grant)

    async def load_access_token(self, token: str) -> AccessToken | None:
        item = self._token(token, "access")
        if item is None or item["expires_at"] <= now() or self._grant_live(item["sub"], item["grant_id"]) is None:
            return None
        return AccessToken(
            token=token,
            client_id=item["client_id"],
            scopes=item["scopes"],
            expires_at=int(item["expires_at"]),
            subject=item["sub"],
            claims={"grant_id": item["grant_id"]},
        )

    # -- the owner's connections ---------------------------------------------------------------------------------------
    def connections(self, sub: str) -> list[dict[str, Any]]:
        rows = self._t.query(
            KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": GRANT + sub}, ConsistentRead=True
        )["Items"]
        live = sorted((r for r in rows if not r["revoked"] and r["expires_at"] > now()), key=lambda r: -r["created_at"])
        return [
            {"id": r["sk"], "name": r["client_name"], "created_at": int(r["created_at"]), "expires_at": int(r["expires_at"])}
            for r in live
        ]

    def disconnect(self, sub: str, grant_id: str) -> None:
        self._revoke(sub, grant_id)  # scoped to the caller's own grants by construction (the key includes their sub)
