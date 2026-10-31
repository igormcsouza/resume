"""The tools are registered on the MCP server only when a store is configured, and stay behind auth."""

import json
import os
from pathlib import Path
from unittest import mock

import boto3
import pytest
from moto import mock_aws

from resume_mcp import handler, load
from resume_mcp.app import build_mcp
from resume_mcp.schema import Master
from resume_mcp.settings import Settings
from resume_mcp.store import Store

from .conftest import FakeJwks, make_token, rpc, running, settings

MASTER = Master.model_validate_json((Path(__file__).parents[2] / "data" / "master.json").read_text())
TOOLS = {
    "get_cv", "get_master", "search_experience", "add_entry", "update_entry",
    "publish", "discard_draft", "history", "rollback", "resync_snapshot",
}  # fmt: skip


@pytest.fixture
def store():
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="sa-east-1").create_table(
            TableName="resume",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="sa-east-1")
        s3.create_bucket(Bucket="bkt", CreateBucketConfiguration={"LocationConstraint": "sa-east-1"})
        s = Store(table, s3, "bkt", "cv.json")
        s.seed(MASTER)
        yield s


async def test_tools_are_registered_only_with_a_store(store):
    assert TOOLS <= {t.name for t in await build_mcp(settings(), jwks=FakeJwks(), store=store).list_tools()}
    assert TOOLS.isdisjoint({t.name for t in await build_mcp(settings(), jwks=FakeJwks()).list_tools()})


async def test_every_store_tool_requires_a_token(store):
    async with running(build_mcp(settings(), jwks=FakeJwks(), store=store)) as c:
        for name in TOOLS:
            r = await c.post("/mcp", **rpc(params={"name": name, "arguments": {}}))
            assert r.status_code == 401, name


async def test_authenticated_call_reaches_the_store(store):
    async with running(build_mcp(settings(), jwks=FakeJwks(), store=store)) as c:
        r = await c.post("/mcp", **rpc(params={"name": "history", "arguments": {}}, token=make_token()))
    assert r.status_code == 200
    assert json.loads(r.json()["result"]["content"][0]["text"]) == {"live_version": 1, "previous_versions": []}


def test_build_store_is_none_without_a_table_and_a_store_with_one():
    base = settings()
    assert handler.build_store(base) is None
    with mock_aws():
        s = handler.build_store(Settings(**{**base.__dict__, "table_name": "t", "bucket_name": "bkt"}))
    assert isinstance(s, Store)


def test_settings_read_the_optional_store_env():
    env = {"ISSUER": "i", "CLIENT_ID": "c", "HOSTED_UI": "h", "TABLE_NAME": "t", "BUCKET_NAME": "b", "SNAPSHOT_KEY": "k"}
    with mock.patch.dict(os.environ, env, clear=True):
        s = Settings.from_env()
    assert (s.table_name, s.bucket_name, s.snapshot_key) == ("t", "b", "k")


def test_load_seeds_the_store_and_publishes_the_first_snapshot(store):
    load.load(store, MASTER)
    assert store.get_live()[1] == 1
    assert store.s3.get_object(Bucket="bkt", Key="cv.json")["Body"].read()
