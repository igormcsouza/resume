"""Pins the final ResumeStack: DynamoDB (with TTL), S3+CloudFront snapshot, MCP Lambda with Citadel sign-in settings."""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from resume_stack import ResumeCertStack, ResumeStack, citadel

CITADEL = {
    "citadel_issuer": "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_TEST",
    "citadel_client_id": "client-1",
    "citadel_domain": "sso.example.test",
    "owner_sub": "owner-sub",
}


def synth(**ctx) -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": [], **CITADEL, **ctx})
    stack = ResumeStack(app, "Resume", env=cdk.Environment(account="000000000000", region="sa-east-1"))
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def t() -> Template:
    return synth()


def only(t, type_):
    found = t.find_resources(type_)
    assert len(found) == 1, f"expected exactly one {type_}, got {len(found)}"
    return next(iter(found.values()))


def test_stack_has_no_user_pool_of_its_own(t):
    assert not t.find_resources("AWS::Cognito::UserPool")
    assert not t.find_resources("AWS::Cognito::UserPoolClient")


def test_missing_citadel_context_fails_the_synth():
    with pytest.raises(ValueError, match="no_such_key"):
        citadel(cdk.App(), "no_such_key")


def test_table_is_on_demand_pitr_and_retained(t):
    r = only(t, "AWS::DynamoDB::Table")
    p = r["Properties"]
    assert p["BillingMode"] == "PAY_PER_REQUEST"
    assert p["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert {(k["AttributeName"], k["KeyType"]) for k in p["KeySchema"]} == {("pk", "HASH"), ("sk", "RANGE")}
    assert r["DeletionPolicy"] == "Retain"
    assert p["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}


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


def test_lambda_is_python_with_store_and_citadel_env(t):
    f = only(t, "AWS::Lambda::Function")["Properties"]
    assert f["Runtime"] == "python3.12" and f["Handler"] == "resume_mcp.handler.handler"
    env = f["Environment"]["Variables"]
    assert {"ISSUER", "CLIENT_ID", "HOSTED_UI", "OWNER_SUBS", "TABLE_NAME", "BUCKET_NAME", "SNAPSHOT_KEY"} <= set(env)
    assert env["ISSUER"] == CITADEL["citadel_issuer"] and env["HOSTED_UI"] == "https://sso.example.test"
    assert env["OWNER_SUBS"] == "owner-sub" and env["SNAPSHOT_KEY"] == "cv.json"
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
    for name in ("McpUrl", "SnapshotUrl", "TableName"):
        t.has_output(name, Match.any_value())


def test_resources_have_readable_names(t):
    assert only(t, "AWS::Lambda::Function")["Properties"]["FunctionName"] == "resume-mcp"
    assert only(t, "AWS::ApiGatewayV2::Api")["Properties"]["Name"] == "resume-mcp-api"


# --- custom domain: certificate stack in us-east-1 + CloudFront alias in the main stack -----------------------
DOMAIN = "resume.igormcsouza.com.br"


def synth_domain():
    app = cdk.App(context={"aws:cdk:bundling-stacks": [], **CITADEL})
    cert = ResumeCertStack(
        app, "ResumeCert", env=cdk.Environment(account="000000000000", region="us-east-1"), cross_region_references=True
    )
    main = ResumeStack(
        app,
        "Resume",
        certificate=cert.certificate,
        env=cdk.Environment(account="000000000000", region="sa-east-1"),
        cross_region_references=True,
    )
    return Template.from_stack(cert), Template.from_stack(main)


@pytest.fixture(scope="module")
def domain():
    return synth_domain()


def test_certificate_is_dns_validated_for_the_domain_in_us_east_1(domain):
    cert, _ = domain
    p = only(cert, "AWS::CertificateManager::Certificate")["Properties"]
    assert p["DomainName"] == DOMAIN and p["ValidationMethod"] == "DNS"
    assert p["DomainValidationOptions"][0]["HostedZoneId"] == "Z08225582X962VWUN2TWM"


def test_cloudfront_serves_the_domain_with_the_certificate_over_modern_tls(domain):
    _, main = domain
    d = only(main, "AWS::CloudFront::Distribution")["Properties"]["DistributionConfig"]
    assert d["Aliases"] == [DOMAIN]
    assert "AcmCertificateArn" in d["ViewerCertificate"]
    assert d["ViewerCertificate"]["MinimumProtocolVersion"] >= "TLSv1.2"


def test_dns_records_alias_the_domain_to_cloudfront(domain):
    _, main = domain
    recs = main.find_resources("AWS::Route53::RecordSet")
    assert {r["Properties"]["Type"] for r in recs.values()} == {"A", "AAAA"}
    assert all(r["Properties"]["Name"] == f"{DOMAIN}." for r in recs.values())
    assert all("AliasTarget" in r["Properties"] for r in recs.values())


def test_stack_without_a_certificate_has_no_alias_or_records(t):
    d = only(t, "AWS::CloudFront::Distribution")["Properties"]["DistributionConfig"]
    assert "Aliases" not in d
    assert not t.find_resources("AWS::Route53::RecordSet")


def test_app_tags_every_stack_with_project():
    import app  # the real entrypoint

    stack = app.app.node.find_child("Resume")
    tags = Template.from_stack(stack).find_resources("AWS::DynamoDB::Table")
    assert tags, "expected a DynamoDB table"
    for r in tags.values():
        assert {"Key": "project", "Value": "resume"} in r["Properties"]["Tags"]
