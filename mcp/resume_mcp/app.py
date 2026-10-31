from urllib.parse import urlsplit

import jwt
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import tools
from .auth import CognitoVerifier
from .settings import Settings


def build_mcp(settings: Settings, jwks=None, store=None) -> FastMCP:
    jwks = jwks or jwt.PyJWKClient(f"{settings.issuer}/.well-known/jwks.json")
    if settings.as_mode == "shim":
        u = urlsplit(settings.resource_url)
        issuer_url = f"{u.scheme}://{u.netloc}"
    else:
        issuer_url = settings.issuer

    mcp = FastMCP(
        "resume-mcp",
        stateless_http=True,
        json_response=True,
        auth=AuthSettings(issuer_url=issuer_url, resource_server_url=settings.resource_url),
        token_verifier=CognitoVerifier(settings, jwks),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def ping() -> str:
        return "pong"

    if store is not None:
        _register_tools(mcp, store)

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def as_metadata(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "issuer": issuer_url,
                "authorization_endpoint": f"{settings.hosted_ui}/oauth2/authorize",
                "token_endpoint": f"{settings.hosted_ui}/oauth2/token",
                "jwks_uri": f"{settings.issuer}/.well-known/jwks.json",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )

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
