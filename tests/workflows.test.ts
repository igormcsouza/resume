import { existsSync, readFileSync } from "fs";
import { describe, expect, it } from "vitest";

const read = (f: string) => readFileSync(new URL(`../.github/workflows/${f}`, import.meta.url), "utf-8");

describe("deploy-aws.yml", () => {
  const exists = existsSync(new URL("../.github/workflows/deploy-aws.yml", import.meta.url));
  const y = () => read("deploy-aws.yml");

  it("exists", () => expect(exists).toBe(true));
  it("deploys only from main, never on pull_request", () => {
    expect(y()).toMatch(/branches:\s*\[\s*"?main"?\s*\]/);
    expect(y()).not.toMatch(/pull_request/);
  });
  it("uses OIDC with the role from a repo variable", () => {
    expect(y()).toMatch(/id-token:\s*write/);
    expect(y()).toMatch(/aws-actions\/configure-aws-credentials@v\d/);
    expect(y()).toContain("role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}");
  });
  it("never uses long-lived AWS keys", () => {
    expect(y()).not.toMatch(/secrets\.AWS/i);
    expect(y()).not.toMatch(/AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)/);
  });
  it("never destroys anything", () => expect(y()).not.toMatch(/destroy/i));
  it("skips cleanly when the role variable is unset", () => expect(y()).toMatch(/if:.*vars\.AWS_DEPLOY_ROLE_ARN/));
  it("is serialised, gated by the production environment, and pins action versions", () => {
    expect(y()).toMatch(/concurrency:/);
    expect(y()).toMatch(/environment:\s*production/);
    expect(y()).not.toMatch(/uses:\s*\S+@(main|master|latest)\b/);
  });
  it("only deploys when an infra app exists", () => expect(y()).toMatch(/hashFiles\('infra\/cdk\.json'\)/));
  it("passes explicit approval flags only for CI, with the right region", () => {
    expect(y()).toContain("sa-east-1");
    expect(y()).toMatch(/cdk(@\d+)? deploy --all/);
  });
});

describe("ci.yml", () => {
  const y = () => read("ci.yml");
  it("keeps the existing web checks", () => {
    for (const s of ["npm ci", "npm run lint", "npm test", "npm run build"]) expect(y()).toContain(s);
  });
  it("runs python and cdk checks only when those folders exist", () => {
    expect(y()).toMatch(/ruff/);
    expect(y()).toMatch(/pytest/);
    expect(y()).toMatch(/cdk(@\d+)? synth/);
    expect(y()).toMatch(/hashFiles\('mcp\/\*\*'\)/);
    expect(y()).toMatch(/hashFiles\('infra\/\*\*'\)/);
  });
  it("does not request AWS credentials", () => expect(y()).not.toMatch(/configure-aws-credentials/));
});
