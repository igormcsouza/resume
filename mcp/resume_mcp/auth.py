import jwt
from mcp.server.auth.provider import AccessToken

from .settings import Settings


class CognitoVerifier:
    def __init__(self, settings: Settings, jwks):
        self.settings, self.jwks = settings, jwks

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],  # never trust the header's alg
                issuer=self.settings.issuer,
                options={"require": ["exp", "iss"]},
            )
            if claims.get("token_use") != "access" or claims.get("client_id") != self.settings.client_id:
                return None
            return AccessToken(
                token=token,
                client_id=claims["client_id"],
                scopes=claims.get("scope", "").split(),
                expires_at=claims["exp"],
            )
        except Exception:  # noqa: BLE001 - any failure (bad token, JWKS outage) is a 401, never a 500
            return None
