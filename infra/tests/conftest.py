"""The real entrypoint (`app.py`) needs the Citadel context that `cdk -c ...` supplies in a deploy.

It must be in the environment before aws_cdk is imported: the jsii runtime snapshots it when it starts.
"""

import json
import os

os.environ["CDK_CONTEXT_JSON"] = json.dumps(
    {
        "aws:cdk:bundling-stacks": [],
        "citadel_issuer": "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_TEST",
        "citadel_client_id": "client-1",
        "citadel_domain": "sso.example.test",
        "owner_sub": "owner-sub",
    }
)
