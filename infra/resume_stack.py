"""Final stack: MCP Lambda with its own OAuth server (sign-in through Citadel), DynamoDB store, S3+CloudFront public CV snapshot, cost budget."""

from pathlib import Path

from aws_cdk import BundlingOptions, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp"
PAGES_ORIGIN = "https://igormcsouza.github.io"
SNAPSHOT_KEY = "cv.json"
API_PATHS = ["/mcp", "/authorize", "/token", "/register", "/oauth/*", "/connections", "/connections/*", "/.well-known/*"]
DOMAIN = "resume.igormcsouza.com.br"
ZONE_NAME = "igormcsouza.com.br"
ZONE_ID = "Z08225582X962VWUN2TWM"  # existing public hosted zone; an id, not a secret


def citadel(scope: Construct, key: str) -> str:
    value = scope.node.try_get_context(key)
    if not value:
        raise ValueError(f"Missing CDK context value '{key}' (the deploy workflow passes it from a repo variable)")
    return str(value)


def _zone(scope: Construct) -> route53.IHostedZone:
    return route53.HostedZone.from_hosted_zone_attributes(scope, "Zone", hosted_zone_id=ZONE_ID, zone_name=ZONE_NAME)


class ResumeCertStack(Stack):
    """CloudFront certificates must live in us-east-1, so this stack is separate from the sa-east-1 one."""

    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        self.certificate = acm.Certificate(
            self, "Cert", domain_name=DOMAIN, validation=acm.CertificateValidation.from_dns(_zone(self))
        )


class ResumeStack(Stack):
    def __init__(self, scope: Construct, id: str, certificate: acm.ICertificate | None = None, **kw) -> None:
        super().__init__(scope, id, **kw)
        reserved = self.node.try_get_context("reserved_concurrency")
        budget_email = self.node.try_get_context("budget_email") or "igormcsouza@gmail.com"

        # Sign-in is Citadel's (the SSO user pool); this stack only needs to know who and where it is.
        issuer, citadel_client = citadel(self, "citadel_issuer"), citadel(self, "citadel_client_id")
        citadel_domain, owner_sub = citadel(self, "citadel_domain"), citadel(self, "owner_sub")

        table = dynamodb.Table(
            self,
            "Table",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="ttl",  # OAuth clients, codes, tokens and grants expire on their own
            removal_policy=RemovalPolicy.RETAIN,
        )
        bucket = s3.Bucket(
            self,
            "Snapshot",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        cors = cloudfront.ResponseHeadersPolicy(
            self,
            "SnapshotCors",
            cors_behavior=cloudfront.ResponseHeadersCorsBehavior(
                access_control_allow_origins=[PAGES_ORIGIN],
                access_control_allow_methods=["GET", "HEAD", "OPTIONS"],
                access_control_allow_headers=["*"],
                access_control_allow_credentials=False,
                origin_override=True,
            ),
        )
        fn = _lambda.Function(
            self,
            "Mcp",
            function_name="resume-mcp",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="resume_mcp.handler.handler",
            code=_lambda.Code.from_asset(
                str(MCP_DIR),
                exclude=["tests", ".venv", "__pycache__"],
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r resume_mcp /asset-output/",
                    ],
                ),
            ),
            # Account quota is 10 and AWS keeps >=10 unreserved, so this stays off until the quota is raised
            # (-c reserved_concurrency=2). The API throttle below bounds concurrency meanwhile.
            reserved_concurrent_executions=int(reserved) if reserved else None,
            timeout=Duration.seconds(15),
            log_group=logs.LogGroup(
                self, "McpLogs", retention=logs.RetentionDays.TWO_WEEKS, removal_policy=RemovalPolicy.DESTROY
            ),
            # No RESOURCE_URL: it would create a CFN cycle with the API; the handler derives it from the request.
            environment={
                "ISSUER": issuer,
                "CLIENT_ID": citadel_client,
                "HOSTED_UI": f"https://{citadel_domain}",
                "OWNER_SUBS": owner_sub,
                **({"PUBLIC_URL": f"https://{DOMAIN}"} if certificate else {}),  # what Claude and Citadel see
                "TABLE_NAME": table.table_name,
                "BUCKET_NAME": bucket.bucket_name,
                "SNAPSHOT_KEY": SNAPSHOT_KEY,
            },
        )
        table.grant_read_write_data(fn)
        bucket.grant_put(fn)
        bucket.grant_read(fn)

        api = apigw.HttpApi(
            self,
            "Api",
            api_name="resume-mcp-api",
            default_integration=HttpLambdaIntegration("McpIntegration", fn),
            create_default_stage=False,
        )
        apigw.HttpStage(
            self,
            "Stage",
            http_api=api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )

        cdn = cloudfront.Distribution(
            self,
            "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=cors,
            ),
            # The MCP and its OAuth server share the domain: these paths go to the API, never cached. Host is not
            # forwarded (API Gateway needs its own); Authorization and the rest are.
            additional_behaviors={
                path: cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(f"{api.api_id}.execute-api.{self.region}.amazonaws.com"),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                )
                for path in API_PATHS
            },
            domain_names=[DOMAIN] if certificate else None,
            certificate=certificate,
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
        )
        if certificate:
            target = route53.RecordTarget.from_alias(targets.CloudFrontTarget(cdn))
            zone = _zone(self)
            route53.ARecord(self, "AliasA", zone=zone, record_name=DOMAIN, target=target)
            route53.AaaaRecord(self, "AliasAaaa", zone=zone, record_name=DOMAIN, target=target)

        budgets.CfnBudget(
            self,
            "Budget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=5, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=budget_email)],
                )
            ],
        )

        CfnOutput(self, "McpUrl", value=f"https://{DOMAIN}/mcp" if certificate else f"{api.api_endpoint}/mcp")
        CfnOutput(self, "SnapshotUrl", value=f"https://{cdn.distribution_domain_name}/{SNAPSHOT_KEY}")
        CfnOutput(self, "TableName", value=table.table_name)
        if certificate:
            CfnOutput(self, "SnapshotDomainUrl", value=f"https://{DOMAIN}/{SNAPSHOT_KEY}")
