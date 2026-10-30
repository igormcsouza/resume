"""Pins the throwaway ResumeSpike stack: a Cognito-protected FastMCP Lambda behind a throttled HTTP API.
Bundling is skipped (aws:cdk:bundling-stacks=[]) so these run without Docker."""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from spike_stack import ResumeSpikeStack

CLAUDE_CALLBACKS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]


@pytest.fixture(scope="module")
def t() -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = ResumeSpikeStack(app, "ResumeSpike", env=cdk.Environment(account="000000000000", region="sa-east-1"))
    return Template.from_stack(stack)


def only(t, type_):
    found = t.find_resources(type_)
    assert len(found) == 1, f"expected exactly one {type_}, got {len(found)}"
    return next(iter(found.values()))["Properties"]


def test_user_pool_is_admin_only_with_totp_mfa(t):
    p = only(t, "AWS::Cognito::UserPool")
    assert p["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert p["MfaConfiguration"] == "ON"
    assert p["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]  # TOTP only, no SMS (SMS costs money)


def test_app_client_is_public_pkce_with_both_claude_callbacks(t):
    p = only(t, "AWS::Cognito::UserPoolClient")
    assert p["GenerateSecret"] is False
    assert p["AllowedOAuthFlows"] == ["code"]
    assert p["AllowedOAuthFlowsUserPoolClient"] is True
    for cb in CLAUDE_CALLBACKS:
        assert cb in p["CallbackURLs"]
    assert "openid" in p["AllowedOAuthScopes"]


def test_hosted_ui_domain_exists(t):
    t.resource_count_is("AWS::Cognito::UserPoolDomain", 1)


def test_lambda_is_python_capped_in_concurrency_and_bundles_nothing_secret(t):
    fns = [r["Properties"] for r in t.find_resources("AWS::Lambda::Function").values()]
    mcp = [f for f in fns if f.get("Handler") == "resume_mcp.handler.handler"]
    assert len(mcp) == 1
    f = mcp[0]
    assert f["Runtime"] == "python3.12"
    assert 1 <= f["ReservedConcurrentExecutions"] <= 5
    env = f["Environment"]["Variables"]
    assert {"ISSUER", "CLIENT_ID", "HOSTED_UI"} <= set(env)
    assert "RESOURCE_URL" not in env  # the API URL is derived from the request domain at runtime (avoids a CFN cycle)


def test_no_wildcard_iam_actions(t):
    """Spike needs no data access: no '*' / 'service:*' actions (the log-retention helper's logs:* style calls are named, not wildcards)."""
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for st in pol["Properties"]["PolicyDocument"]["Statement"]:
            actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
            for action in actions:
                assert action != "*" and not action.endswith(":*"), action
            assert not any(a.startswith(("dynamodb:", "s3:")) for a in actions)


def test_http_api_stage_is_throttled(t):
    stages = t.find_resources("AWS::ApiGatewayV2::Stage")
    assert len(stages) == 1
    s = next(iter(stages.values()))["Properties"]["DefaultRouteSettings"]
    assert 0 < s["ThrottlingRateLimit"] <= 10
    assert 0 < s["ThrottlingBurstLimit"] <= 20


def test_api_routes_everything_to_the_lambda(t):
    routes = [r["Properties"]["RouteKey"] for r in t.find_resources("AWS::ApiGatewayV2::Route").values()]
    assert "$default" in routes or any("mcp" in r for r in routes)
    t.resource_count_is("AWS::ApiGatewayV2::Integration", 1)


def test_log_retention_is_bounded(t):
    t.has_resource_properties("Custom::LogRetention", {"RetentionInDays": Match.any_value()}) if t.find_resources(
        "Custom::LogRetention"
    ) else t.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": Match.any_value()})


def test_spike_is_fully_destroyable(t):
    for res in t.to_json()["Resources"].values():
        assert res.get("DeletionPolicy") != "Retain", res["Type"]
        assert res.get("UpdateReplacePolicy") != "Retain", res["Type"]


def test_outputs_needed_for_the_phone_test(t):
    outs = t.to_json()["Outputs"]
    for name in ("McpUrl", "UserPoolId", "ClientId", "HostedUi", "Issuer"):
        assert name in outs, name
