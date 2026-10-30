from urllib.parse import urlsplit

import jwt
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import CognitoVerifier
from .settings import Settings


def build_mcp(settings: Settings, jwks=None) -> FastMCP:
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
