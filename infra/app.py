import os

import aws_cdk as cdk

from resume_stack import ResumeCertStack, ResumeStack

app = cdk.App()
account = os.environ.get("CDK_DEFAULT_ACCOUNT")
cert = ResumeCertStack(
    app, "ResumeCert", env=cdk.Environment(account=account, region="us-east-1"), cross_region_references=True
)
ResumeStack(
    app,
    "Resume",
    certificate=cert.certificate,
    env=cdk.Environment(account=account, region="sa-east-1"),
    cross_region_references=True,
)
app.synth()
