import dataclasses

from mangum import Mangum

from .app import build_mcp
from .settings import Settings


def handler(event, context):
    s = Settings.from_env()
    if not s.resource_url:
        s = dataclasses.replace(s, resource_url=f"https://{event['requestContext']['domainName']}/mcp")
    # fresh app per invocation: the SDK session manager can only run once per instance
    return Mangum(build_mcp(s).streamable_http_app(), lifespan="auto")(event, context)
