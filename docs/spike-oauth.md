# Spike: claude.ai custom connector against Cognito

Result: **works** (2026-10-31). The claude.ai connector completes OAuth against Cognito and calls the
`ping` tool from desktop and from a fresh chat, with the login persisted.

## Working setup
- Remote MCP (FastMCP, stateless streamable HTTP) on Lambda behind an HTTP API, `ResumeSpike` stack, sa-east-1.
- Cognito user pool, admin-created users only, public app client with PKCE, callbacks
  `https://claude.ai/api/mcp/auth_callback` and `https://claude.com/api/mcp/auth_callback`.
- Connector added with the MCP URL and the app client ID as a manual client, no secret.
- `AS_MODE=shim` is required (see below).

## Findings
- **Cognito discovery fails the first attempt.** The protected-resource metadata named the Cognito issuer as
  the authorization server. Cognito answers `400` to `/.well-known/oauth-authorization-server` (it only serves
  `openid-configuration`), so claude.ai showed "Authorization failed" before opening a login page.
  Fix: advertise our own origin as the authorization server and serve RFC 8414 metadata from a shim route that
  points at the Cognito hosted UI endpoints (PR #25).
- Tokens are verified in the Lambda (RS256, issuer, `token_use=access`, `client_id`); no token gets 401 with a
  `WWW-Authenticate` header pointing at the resource metadata.
- With a manual client ID, no dynamic client registration is needed.
- GitHub OIDC for deploys: the job runs in the `production` environment and the repo uses immutable subjects, so
  the role trust must use `repo:<owner>@<id>/<repo>@<id>:environment:production`.

## Not yet verified
- Token refresh after the access token expires (default 1 hour) and after a full app restart.
- Behaviour on the phone app specifically (the connector is account-level, so it should be the same).

## Decisions for the final stack
- Keep the shim; reuse the auth code from `mcp/resume_mcp`.
- Password-only login (no MFA) for the single owner; API throttling and the draft/publish split bound abuse.
- Destroy `ResumeSpike` by hand when the final stack replaces it (the workflow never destroys).
