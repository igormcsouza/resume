"""Throwaway spike: Cognito-protected FastMCP Lambda behind a throttled HTTP API. Fully destroyable."""

from pathlib import Path

from aws_cdk import BundlingOptions, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp"
CLAUDE_CALLBACKS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]


class ResumeSpikeStack(Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)

        pool = cognito.UserPool(
            self,
            "Pool",
            self_sign_up_enabled=False,
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            removal_policy=RemovalPolicy.DESTROY,
        )
        client = pool.add_client(
            "Client",
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID],
                callback_urls=CLAUDE_CALLBACKS,
            ),
        )
        domain = pool.add_domain(
            "Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"resume-spike-{self.account}")
        )
        issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}"

        fn = _lambda.Function(
            self,
            "Mcp",
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
            reserved_concurrent_executions=2,
            timeout=Duration.seconds(15),
            log_retention=logs.RetentionDays.TWO_WEEKS,
            # No RESOURCE_URL: it would create a CFN cycle with the API; the handler derives it from the request.
            environment={"ISSUER": issuer, "CLIENT_ID": client.user_pool_client_id, "HOSTED_UI": domain.base_url()},
        )

        api = apigw.HttpApi(
            self,
            "Api",
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

        CfnOutput(self, "McpUrl", value=f"{api.api_endpoint}/mcp")
        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "ClientId", value=client.user_pool_client_id)
        CfnOutput(self, "HostedUi", value=domain.base_url())
        CfnOutput(self, "Issuer", value=issuer)
