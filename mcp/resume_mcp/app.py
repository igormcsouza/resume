from html import escape
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.routes import build_metadata
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import citadel, tools
from .oauth import SCOPE, Oauth
from .settings import Settings

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
# The consent page may only post back to itself and hand the browser to Claude's callback.
PAGE_HEADERS = {
    **NO_STORE,
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://claude.ai https://claude.com; frame-ancestors 'none'",
}


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>body{{font:16px system-ui;max-width:28rem;margin:4rem auto;padding:0 1rem}}"
        f"button{{font:inherit;padding:.5rem 1rem;margin-right:.5rem}}</style><h1>{escape(title)}</h1>{body}"
    )
    return HTMLResponse(html, status_code=status, headers=PAGE_HEADERS)


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


class ResumeMCP(FastMCP):
    def streamable_http_app(self):
        app = super().streamable_http_app()
        a = self.settings.auth

        async def metadata(request: Request) -> Response:
            # The SDK advertises only secret-based client auth; ours are public PKCE clients, which Claude must know.
            m = build_metadata(a.issuer_url, None, a.client_registration_options, RevocationOptions())
            m.token_endpoint_auth_methods_supported = ["none"]
            return JSONResponse(m.model_dump(mode="json", exclude_none=True), headers={"Access-Control-Allow-Origin": "*"})

        app.router.routes.insert(0, Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]))
        return app


def build_mcp(settings: Settings, oauth: Oauth, jwks=None, store=None) -> FastMCP:
    jwks = jwks or jwt.PyJWKClient(f"{settings.issuer}/.well-known/jwks.json")
    u = urlsplit(settings.resource_url)

    mcp = ResumeMCP(
        "resume-mcp",
        stateless_http=True,
        json_response=True,
        auth_server_provider=oauth,
        auth=AuthSettings(
            issuer_url=f"{u.scheme}://{u.netloc}",  # we are our own authorization server
            resource_server_url=settings.resource_url,
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
            required_scopes=[SCOPE],
            validate_token_resource=False,  # every token we accept is one we issued, for this server only
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def ping() -> str:
        return "pong"

    if store is not None:
        _register_tools(mcp, store)

    # -- sign-in and consent: the browser leg between /authorize and Claude's callback ----------------------------------
    @mcp.custom_route("/oauth/callback", methods=["GET"])
    async def callback(request: Request) -> Response:
        pending_id, code = request.query_params.get("state", ""), request.query_params.get("code", "")
        item = oauth.pending(pending_id)
        if item is None or not code:
            return _page("Sign-in failed", "<p>This request is invalid or expired. Start again from Claude.</p>", 400)
        try:
            sub = citadel.identify(settings, jwks, code, item["verifier"], oauth.callback_url)
        except Exception:  # noqa: BLE001 - any failure (bad code, outage, bad token) is just "sign-in failed"
            return _page("Sign-in failed", "<p>Could not verify your sign-in. Start again from Claude.</p>", 400)
        if sub not in settings.owner_subs:
            return _page("Not allowed", "<p>This account cannot connect to this server.</p>", 403)
        if not oauth.signed_in(pending_id, sub):
            return _page("Sign-in failed", "<p>This request is invalid or expired. Start again from Claude.</p>", 400)
        client = await oauth.get_client(item["client_id"])
        name = escape(client.client_name if client else "an app")
        return _page(
            "Connect to Resume",
            f"<p><b>{name}</b> wants to read and edit your resume.</p>"
            f"<form method=post action=/oauth/consent><input type=hidden name=state value='{escape(pending_id)}'>"
            "<button name=decision value=approve>Approve</button><button name=decision value=deny>Deny</button></form>",
        )

    @mcp.custom_route("/oauth/consent", methods=["POST"])
    async def consent(request: Request) -> Response:
        form = await request.form()
        url = oauth.decide(str(form.get("state", "")), form.get("decision") == "approve")
        if url is None:
            return _page("Request expired", "<p>This request is invalid or expired. Start again from Claude.</p>", 400)
        return RedirectResponse(url, status_code=303, headers=NO_STORE)

    # -- the owner's connections: any connected client's token may list and revoke ---------------------------------------
    async def _caller(request: Request) -> AccessToken | None:
        return await oauth.load_access_token(_bearer(request))

    @mcp.custom_route("/connections", methods=["GET"])
    async def list_connections(request: Request) -> Response:
        me = await _caller(request)
        if me is None:
            return JSONResponse({"error": "invalid_token"}, 401, {**NO_STORE, "WWW-Authenticate": "Bearer"})
        rows = [{**c, "current": c["id"] == me.claims["grant_id"]} for c in oauth.connections(me.subject)]
        return JSONResponse({"connections": rows}, headers=NO_STORE)

    @mcp.custom_route("/connections/{grant_id}", methods=["DELETE"])
    async def disconnect(request: Request) -> Response:
        me = await _caller(request)
        if me is None:
            return JSONResponse({"error": "invalid_token"}, 401, {**NO_STORE, "WWW-Authenticate": "Bearer"})
        oauth.disconnect(me.subject, request.path_params["grant_id"])
        return Response(status_code=204, headers=NO_STORE)

    return mcp


def _register_tools(mcp: FastMCP, store) -> None:
    @mcp.tool()
    def get_cv() -> dict:
        """Get the LIVE public CV (what the website shows) and its version. Private entries are never included."""
        return tools.get_cv(store)

    @mcp.tool()
    def get_master() -> dict:
        """Get the full DRAFT master (all entries, including private and non-general) with draft and live versions."""
        return tools.get_master(store)

    @mcp.tool()
    def search_experience(query: str, limit: int = 20) -> list[dict]:
        """Search the DRAFT master (private included) by text in any language, tags or meta values, case-insensitive."""
        return tools.search_experience(store, query, limit)

    @mcp.tool()
    def add_entry(entry: dict) -> dict:
        """Add one entry to the DRAFT. Needs id, kind and usually text; parent must exist and tags be in tag_vocab.
        Returns the new draft_version. Nothing is public until publish()."""
        return tools.add_entry(store, entry)

    @mcp.tool()
    def update_entry(id: str, fields: dict) -> dict:
        """Merge fields (text, tags, visibility, general, roles, meta, order, status, parent, notes) into a DRAFT entry.
        id and kind cannot change. Returns the new draft_version."""
        return tools.update_entry(store, id, fields)

    @mcp.tool()
    def publish(draft_version: int) -> dict:
        """Make the DRAFT live and refresh the public snapshot. Pass the draft_version you last saw; stale means conflict."""
        return tools.publish(store, draft_version)

    @mcp.tool()
    def discard_draft() -> dict:
        """Throw away unpublished changes by resetting the DRAFT to the LIVE master."""
        return tools.discard_draft(store)

    @mcp.tool()
    def history() -> dict:
        """List the live version and the previous (rollback-able) versions, newest first."""
        return tools.history(store)

    @mcp.tool()
    def rollback(version: int) -> dict:
        """Load a previous version into the DRAFT (live is unchanged until publish())."""
        return tools.rollback(store, version)

    @mcp.tool()
    def resync_snapshot() -> dict:
        """Re-write the public S3 snapshot from the LIVE master, e.g. after a failed upload."""
        return tools.resync_snapshot(store)
