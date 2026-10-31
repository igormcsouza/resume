# Resume backend runbook

Source of truth is DynamoDB; the page reads a static snapshot. Connection details: `docs/mcp-connection.md`.
Design history: `docs/spike-oauth.md` and the gru log.

## Layout

| Piece | Where |
|---|---|
| Page | GitHub Pages, `igormcsouza.github.io/resume`, reads `https://resume.igormcsouza.com.br/cv.json` at runtime and falls back to the bundled `lib/cv.json` |
| Snapshot | S3 (private) behind CloudFront + OAC, domain `resume.igormcsouza.com.br` (Route53 zone `igormcsouza.com.br`) |
| Store | DynamoDB `Resume-Table…`: pk `MASTER`, sk `DRAFT` / `LIVE` / `HIST#<version>` |
| MCP | Lambda `resume-mcp` behind HTTP API `resume-mcp-api` (throttle 5 rps, burst 10), Cognito OAuth |
| Stacks | `Resume` (sa-east-1), `ResumeCert` (us-east-1, CloudFront certificate) |
| Code | `infra/` (CDK Python), `mcp/` (Lambda), `data/master.json` (seed) |

Stack, table and bucket are `RETAIN`: deleting a stack never deletes data.

## Deploy

Only from GitHub Actions (`Deploy AWS`, OIDC role `resume-github-deploy`, environment `production`).
It runs on push to `main` touching `infra/**` or `mcp/**`, or by hand:

```bash
gh workflow run "Deploy AWS" --repo igormcsouza/resume
```

Never `cdk deploy` from a laptop or an agent. The workflow never destroys anything.
Check before merging: `ruff check` + `pytest` in `mcp/` and `infra/`, `cdk synth` in `infra/`.

## Day to day: change the CV

Ask Claude (desktop or phone, connector "Resume"). Flow:

1. `search_experience` / `get_master` to read.
2. `add_entry` / `update_entry` write a **draft** (optimistic version check; a `Conflict` means re-read and retry).
3. `publish(draft_version)` promotes the draft to LIVE, keeps `HIST#<n>`, and rewrites `cv.json`.
4. The page shows it on next load (snapshot is `no-cache`). No redeploy.

Only entries that are `status: live`, `visibility: public` and `general: true` reach the snapshot. Private or
tailored-only entries stay in DynamoDB.

## Recover

| Problem | Fix |
|---|---|
| Bad publish | `history`, then `rollback` to a previous version |
| Unwanted draft | `discard_draft` |
| Snapshot older than LIVE (S3 upload failed, next publish says "nothing to publish") | `resync_snapshot` |
| Table lost or empty | restore from PITR (35 days), or reseed (below) |
| Snapshot bucket object deleted | `resync_snapshot` (bucket is versioned too) |

## Seed or reload from `data/master.json`

Only for an empty store (`seed` does nothing if the master exists). User's terminal, own AWS profile:

```bash
cd mcp && pip install -r requirements.txt
TABLE_NAME=<TableName output> BUCKET_NAME=<bucket> AWS_REGION=sa-east-1 python -m resume_mcp.load
```

Table name: `aws cloudformation describe-stacks --stack-name Resume --region sa-east-1 --query 'Stacks[0].Outputs'`.

## Users and auth

- Admin-created users only; no self sign-up, no MFA, password min 12. Refresh token 90 days, access token 60 min.
- Create or reset a user in the Cognito console (pool `resume-user-pool`) or with `aws cognito-idp admin-create-user` /
  `admin-set-user-password --permanent`. The owner types the password; agents never see or store it.
- A new client (not claude.ai) needs its callback URL added to the app client in `infra/resume_stack.py`.
- Cognito traps: the hosted UI domain prefix cannot change in place (the deploy rolls back); changing it means a
  replacement and a new connector.

## Abuse and cost

- Public read hits CloudFront + S3 only (no compute). MCP needs a valid Cognito token; API throttle caps the rest.
- Budget alarm 5 USD/month, email at 80%.
- Lambda account concurrency quota is 10; optional cap: CDK context `reserved_concurrency` (the workflow does not set it; add `-c reserved_concurrency=N` to its deploy step).

## Known gaps

- Token refresh after the 1 h access token expiry is not yet confirmed on the final connector.
- Table and bucket keep CDK-generated names (renaming needs replacement and a data reload).
