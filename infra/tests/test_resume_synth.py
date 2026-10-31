"""Pins the final ResumeStack: Cognito (password-only, long refresh), DynamoDB, S3+CloudFront snapshot, MCP Lambda."""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from resume_stack import ResumeStack

CLAUDE_CALLBACKS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]
UNIT_MINUTES = {"minutes": 1, "hours": 60, "days": 1440}


def synth(**ctx) -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": [], **ctx})
    stack = ResumeStack(app, "Resume", env=cdk.Environment(account="000000000000", region="sa-east-1"))
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def t() -> Template:
    return synth()


def only(t, type_):
    found = t.find_resources(type_)
    assert len(found) == 1, f"expected exactly one {type_}, got {len(found)}"
    return next(iter(found.values()))


def minutes(client, kind):
    unit = client.get("TokenValidityUnits", {}).get(f"{kind}Token", "minutes" if kind != "Refresh" else "days")
    return client[f"{kind}TokenValidity"] * UNIT_MINUTES[unit]


def test_user_pool_is_admin_only_password_only_and_retained(t):
    r = only(t, "AWS::Cognito::UserPool")
    p = r["Properties"]
    assert p["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert p["MfaConfiguration"] == "OFF"
    assert p["Policies"]["PasswordPolicy"]["MinimumLength"] >= 12
    assert r["DeletionPolicy"] == "Retain"


def test_app_client_is_public_pkce_with_30_day_plus_refresh(t):
    p = only(t, "AWS::Cognito::UserPoolClient")["Properties"]
    assert p["GenerateSecret"] is False
    assert p["AllowedOAuthFlows"] == ["code"]
    assert sorted(p["CallbackURLs"]) == sorted(CLAUDE_CALLBACKS)
    assert minutes(p, "Refresh") >= 30 * 1440
    assert minutes(p, "Access") <= 60  # short-lived access tokens, long-lived refresh


def test_table_is_on_demand_pitr_and_retained(t):
    r = only(t, "AWS::DynamoDB::Table")
    p = r["Properties"]
    assert p["BillingMode"] == "PAY_PER_REQUEST"
    assert p["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert {(k["AttributeName"], k["KeyType"]) for k in p["KeySchema"]} == {("pk", "HASH"), ("sk", "RANGE")}
    assert r["DeletionPolicy"] == "Retain"


def test_snapshot_bucket_is_private_versioned_and_only_cloudfront_reads_it(t):
    p = only(t, "AWS::S3::Bucket")["Properties"]
    assert all(p["PublicAccessBlockConfiguration"].values()) and len(p["PublicAccessBlockConfiguration"]) == 4
    assert p["VersioningConfiguration"]["Status"] == "Enabled"
    pol = only(t, "AWS::S3::BucketPolicy")["Properties"]["PolicyDocument"]["Statement"]
    allows = [s for s in pol if s["Effect"] == "Allow"]
    assert all(s["Principal"] not in ("*", {"AWS": "*"}) for s in allows)  # the enforce_ssl Deny may use a wildcard
    assert any(s["Principal"] == {"Service": "cloudfront.amazonaws.com"} for s in pol)


def test_cloudfront_uses_oac_https_only_and_cors_for_the_github_pages_origin(t):
    only(t, "AWS::CloudFront::OriginAccessControl")
    d = only(t, "AWS::CloudFront::Distribution")["Properties"]["DistributionConfig"]
    assert d["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    cors = only(t, "AWS::CloudFront::ResponseHeadersPolicy")["Properties"]["ResponseHeadersPolicyConfig"]["CorsConfig"]
    assert cors["AccessControlAllowOrigins"]["Items"] == ["https://igormcsouza.github.io"]
    assert set(cors["AccessControlAllowMethods"]["Items"]) <= {"GET", "HEAD", "OPTIONS"}


def test_lambda_is_python_with_store_and_cognito_env_and_shim(t):
    f = only(t, "AWS::Lambda::Function")["Properties"]
    assert f["Runtime"] == "python3.12" and f["Handler"] == "resume_mcp.handler.handler"
    env = f["Environment"]["Variables"]
    assert {"ISSUER", "CLIENT_ID", "HOSTED_UI", "TABLE_NAME", "BUCKET_NAME", "SNAPSHOT_KEY"} <= set(env)
    assert env["AS_MODE"] == "shim" and env["SNAPSHOT_KEY"] == "cv.json"
    assert "RESOURCE_URL" not in env
    assert "ReservedConcurrentExecutions" not in f


def test_reserved_concurrency_is_opt_in():
    f = only(synth(reserved_concurrency="3"), "AWS::Lambda::Function")["Properties"]
    assert f["ReservedConcurrentExecutions"] == 3


def test_lambda_permissions_have_no_wildcard_actions_or_resources_for_data(t):
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for s in pol["Properties"]["PolicyDocument"]["Statement"]:
            actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            assert not any(a == "*" or a.endswith(":*") for a in actions), actions
            if any(a.startswith(("dynamodb:", "s3:")) for a in actions):
                assert s["Resource"] != "*"


def test_api_is_throttled(t):
    stage = only(t, "AWS::ApiGatewayV2::Stage")["Properties"]["DefaultRouteSettings"]
    assert stage["ThrottlingRateLimit"] <= 10 and stage["ThrottlingBurstLimit"] <= 20


def test_budget_alarm_emails_the_owner(t):
    b = only(t, "AWS::Budgets::Budget")["Properties"]
    assert b["Budget"]["TimeUnit"] == "MONTHLY" and b["Budget"]["BudgetLimit"]["Amount"] <= 10
    assert any(s["SubscriptionType"] == "EMAIL" for n in b["NotificationsWithSubscribers"] for s in n["Subscribers"])


def test_outputs(t):
    for name in ("McpUrl", "UserPoolId", "ClientId", "HostedUi", "Issuer", "SnapshotUrl", "TableName"):
        t.has_output(name, Match.any_value())


def test_resources_have_readable_names(t):
    assert only(t, "AWS::Cognito::UserPool")["Properties"]["UserPoolName"] == "resume-user-pool"
    assert only(t, "AWS::Cognito::UserPoolDomain")["Properties"]["Domain"].startswith("resume-auth-")
    assert only(t, "AWS::Lambda::Function")["Properties"]["FunctionName"] == "resume-mcp"
    assert only(t, "AWS::ApiGatewayV2::Api")["Properties"]["Name"] == "resume-mcp-api"
