# Resume agent notes

## Dev team specifics
- Stack and layout: Next.js static export on GitHub Pages (root: `app/`, `components/`, `lib/`); AWS backend: CDK Python in `infra/`, Python MCP Lambda in `mcp/`, seed data in `data/master.json`. DynamoDB is the CV source of truth; the page reads the public snapshot at runtime.
- Check commands: `npm run lint`, `npm test` (vitest), `npm run build`. Backend: `ruff check` + `pytest` in `mcp/` and `infra/`, `cdk synth` in `infra/`.
- E2E/manual QA: `npm run dev` (port 5600) or `docker compose up` (port 12001), open `/en/` and print to PDF. Backend: connect the claude.ai connector from a phone.
- Branch/commit/PR style: branch per task, short imperative commit titles (see `git log`), one PR per task; PO merges.
- Delivery mode: PR per task.
- Hard stops (PO's OK): Tier 3 models, anything that deploys to AWS (deploys run only from GitHub Actions via OIDC, never from an agent), changes to prod auth, deleting data, force push.
- Design docs: plan and decisions live in the gru log (`.claude/gru/active/resume-backend-mcp.md`); operations in `docs/runbook.md`, connector info in `docs/mcp-connection.md`.
- gru store: `.claude/gru/`
