import os

import aws_cdk as cdk

from resume_stack import ResumeStack
from spike_stack import ResumeSpikeStack

app = cdk.App()
ResumeSpikeStack(
    app, "ResumeSpike", env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="sa-east-1")
)
ResumeStack(app, "Resume", env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="sa-east-1"))
app.synth()
