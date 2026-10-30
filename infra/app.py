import os

import aws_cdk as cdk

from spike_stack import ResumeSpikeStack

app = cdk.App()
ResumeSpikeStack(
    app, "ResumeSpike", env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="sa-east-1")
)
app.synth()
