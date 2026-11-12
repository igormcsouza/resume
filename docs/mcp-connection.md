# Resume MCP: connection info

Remote MCP server for the resume (stack `Resume`, region sa-east-1). Nothing here is secret. The backend is used by
Claude only: the web page just reads the public snapshot and never talks to it.

| | |
|---|---|
| MCP URL | `https://resume.igormcsouza.com.br/mcp` (CloudFront sends the MCP and OAuth paths to the API; everything else is the public snapshot) |
| Add to Claude | the URL only. Claude registers itself, no client id to paste |
| Sign-in | Citadel (`sso.citadel.igormcsouza.com.br`), the owner's account, then an Approve screen |
| Public snapshot | `https://resume.igormcsouza.com.br/cv.json` (CORS: `https://igormcsouza.github.io`; the raw CloudFront address is in the `SnapshotUrl` stack output) |

The API's own `execute-api` address (stack output) still answers, but advertises the custom domain; always use the custom one. Values change if the stack is replaced; re-read them with:

```bash
aws cloudformation describe-stacks --stack-name Resume --region sa-east-1 --query 'Stacks[0].Outputs'
```

## Add it to claude.ai (desktop or phone)
Settings → Connectors → Add custom connector, paste the URL, leave the advanced settings alone. A Citadel sign-in
opens; after it, an Approve / Deny page names the app asking for access. Connectors belong to the account, so it
then shows on every device. Each Claude account connects separately and can be revoked alone.

## How the sign-in works
The Lambda is its own OAuth 2.1 server (the MCP SDK's routes plus `mcp/resume_mcp/oauth.py`); Citadel only proves who
the owner is.
- `GET /.well-known/oauth-protected-resource/mcp` and `/.well-known/oauth-authorization-server` are the discovery
  documents. A request with no token gets `401` and a `WWW-Authenticate` header with the metadata URL.
- `POST /register` is open (dynamic client registration) but only accepts the two Claude callbacks
  (`https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`), public clients only, 30
  registrations per hour.
- `GET /authorize` parks the request and sends the browser to Citadel. Citadel returns to `/oauth/callback`, which
  checks the ID token and that the user is the owner (`OWNER_SUBS`), then shows the Approve page.
  `POST /oauth/consent` issues a one-minute, single-use code; `POST /token` trades it (PKCE S256) for a 1 h access
  token and a 90-day refresh token, rotated on every use.
- Codes and tokens are stored as SHA-256 digests in the Resume table (keys `MCP*#`, expiring through the `ttl`
  attribute). Reusing a code or a rotated refresh token revokes that grant.

## Connections endpoint
`GET /connections` returns the grants (one per connected Claude account), newest first, never any token:

```bash
curl -H "Authorization: Bearer <access token>" https://resume.igormcsouza.com.br/connections
# {"connections":[{"id":"...","name":"Claude","created_at":1762...,"expires_at":1770...,"current":true}]}
```

`DELETE /connections/<id>` revokes one grant (204; its access and refresh tokens stop working at once). Both need the
access token of any connected client; `current` marks the grant of the token used for the call. There is no page for
it: ask Claude to call it, or use `curl`.

Tools: `get_cv`, `get_master`, `search_experience`, `add_entry`, `update_entry`, `publish(draft_version)`,
`discard_draft`, `history`, `rollback`, `resync_snapshot`, `ping`. Writes go to a draft; only `publish` changes the
public snapshot.
