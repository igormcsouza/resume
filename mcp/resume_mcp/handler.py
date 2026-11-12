import dataclasses
from urllib.parse import urlsplit

import boto3
from mangum import Mangum

from .app import build_mcp
from .oauth import Oauth
from .settings import Settings
from .store import Store


def build_store(s: Settings) -> Store | None:
    if not s.table_name:
        return None
    return Store(boto3.resource("dynamodb").Table(s.table_name), boto3.client("s3"), s.bucket_name, s.snapshot_key)


def build_oauth(s: Settings) -> Oauth:
    u = urlsplit(s.resource_url)
    return Oauth(boto3.resource("dynamodb").Table(s.table_name), f"{u.scheme}://{u.netloc}", s.hosted_ui, s.client_id)


def handler(event, context):
    s = Settings.from_env()
    if not s.resource_url:
        s = dataclasses.replace(s, resource_url=f"https://{event['requestContext']['domainName']}/mcp")
    # fresh app per invocation: the SDK session manager can only run once per instance
    return Mangum(build_mcp(s, build_oauth(s), store=build_store(s)).streamable_http_app(), lifespan="auto")(event, context)
