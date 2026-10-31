import os

import aws_cdk as cdk

from resume_stack import ResumeStack

app = cdk.App()
ResumeStack(app, "Resume", env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="sa-east-1"))
app.synth()
