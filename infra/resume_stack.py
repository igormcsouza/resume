"""Final stack: Cognito-protected MCP Lambda, DynamoDB store, S3+CloudFront public CV snapshot, cost budget."""

from pathlib import Path

from aws_cdk import BundlingOptions, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp"
CLAUDE_CALLBACKS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]
PAGES_ORIGIN = "https://igormcsouza.github.io"
SNAPSHOT_KEY = "cv.json"


class ResumeStack(Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        reserved = self.node.try_get_context("reserved_concurrency")
        budget_email = self.node.try_get_context("budget_email") or "igormcsouza@gmail.com"

        pool = cognito.UserPool(
            self,
            "Pool",
            user_pool_name="resume-user-pool",
            self_sign_up_enabled=False,
            mfa=cognito.Mfa.OFF,
            password_policy=cognito.PasswordPolicy(min_length=12),
            removal_policy=RemovalPolicy.RETAIN,
        )
        client = pool.add_client(
            "Client",
            generate_secret=False,
            refresh_token_validity=Duration.days(90),
            access_token_validity=Duration.minutes(60),
            id_token_validity=Duration.minutes(60),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID],
                callback_urls=CLAUDE_CALLBACKS,
            ),
        )
        domain = pool.add_domain(
            "Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"resume-{self.account}")
        )
        issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}"

        table = dynamodb.Table(
            self,
            "Table",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
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
        cdn = cloudfront.Distribution(
            self,
            "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=cors,
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
            # AS_MODE=shim: Cognito answers 400 to oauth-authorization-server, so advertise our own metadata route.
            environment={
                "ISSUER": issuer,
                "CLIENT_ID": client.user_pool_client_id,
                "HOSTED_UI": domain.base_url(),
                "AS_MODE": "shim",
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

        CfnOutput(self, "McpUrl", value=f"{api.api_endpoint}/mcp")
        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "ClientId", value=client.user_pool_client_id)
        CfnOutput(self, "HostedUi", value=domain.base_url())
        CfnOutput(self, "Issuer", value=issuer)
        CfnOutput(self, "SnapshotUrl", value=f"https://{cdn.distribution_domain_name}/{SNAPSHOT_KEY}")
        CfnOutput(self, "TableName", value=table.table_name)
