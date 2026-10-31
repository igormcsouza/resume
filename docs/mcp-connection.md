# Resume MCP: connection info

Remote MCP server for the resume (stack `Resume`, region sa-east-1). Nothing here is secret: the OAuth client is
public (PKCE, no client secret). The password for user `walkdead` is **not** stored anywhere in this repo; it
lives in the owner's password manager.

| | |
|---|---|
| MCP URL | `https://atkcomv38d.execute-api.sa-east-1.amazonaws.com/mcp` |
| OAuth client ID | `49cp4g3ato1ikqa33513lvlklp` (no client secret) |
| Login | user `walkdead`, password only (no MFA) |
| User pool | `resume-user-pool` (`sa-east-1_k3WHIm3Xx`) |
| Hosted UI | `https://resume-693473496042.auth.sa-east-1.amazoncognito.com` |
| Public snapshot | `https://d1degxrowcwctx.cloudfront.net/cv.json` (CORS: `https://igormcsouza.github.io`) |
| Callbacks allowed | `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback` |

Values change if the stack is replaced; re-read them with:

```bash
aws cloudformation describe-stacks --stack-name Resume --region sa-east-1 --query 'Stacks[0].Outputs'
```

## Add it to claude.ai (desktop or phone)
Settings → Connectors → Add custom connector. URL as above; under advanced settings set the OAuth client ID and
leave the secret empty. Sign in as `walkdead`. Connectors belong to the account, so it then shows on every device.

## Add it to another agent or client
Any MCP client that supports remote streamable-HTTP servers with OAuth 2.1 (authorization code + PKCE) works:
give it the MCP URL and the client ID. Discovery is automatic:
- `GET <api>/.well-known/oauth-protected-resource/mcp` names the API host as the authorization server.
- `GET <api>/.well-known/oauth-authorization-server` is a shim that points at the Cognito hosted UI
  (Cognito itself does not serve that document; see `docs/spike-oauth.md`).
- The client must allow the redirect URI it uses; only the two claude callbacks above are registered, so other
  clients need their callback URL added to the app client in `infra/resume_stack.py` first.
- A request with no token gets `401` and a `WWW-Authenticate` header with the metadata URL.

Tools: `get_cv`, `get_master`, `search_experience`, `add_entry`, `update_entry`, `publish(draft_version)`,
`discard_draft`, `history`, `rollback`, `resync_snapshot`, `ping`. Writes go to a draft; only `publish` changes the
public snapshot.
