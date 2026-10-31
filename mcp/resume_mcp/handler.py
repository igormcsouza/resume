import dataclasses

import boto3
from mangum import Mangum

from .app import build_mcp
from .settings import Settings
from .store import Store


def build_store(s: Settings) -> Store | None:
    if not s.table_name:
        return None
    return Store(boto3.resource("dynamodb").Table(s.table_name), boto3.client("s3"), s.bucket_name, s.snapshot_key)


def handler(event, context):
    s = Settings.from_env()
    if not s.resource_url:
        s = dataclasses.replace(s, resource_url=f"https://{event['requestContext']['domainName']}/mcp")
    # fresh app per invocation: the SDK session manager can only run once per instance
    return Mangum(build_mcp(s, store=build_store(s)).streamable_http_app(), lifespan="auto")(event, context)
