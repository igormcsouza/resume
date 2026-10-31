"""Store contract: one DRAFT and one LIVE master in DynamoDB, a public snapshot in S3, optimistic versions."""

import json
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from resume_mcp import snapshot
from resume_mcp.project import project
from resume_mcp.schema import Entry, Master
from resume_mcp.store import Conflict, Store

MASTER = Master.model_validate_json((Path(__file__).parents[2] / "data" / "master.json").read_text())
BUCKET, KEY = "resume-snapshot", "cv.json"
SECRET = "SENTINEL-PRIVATE-9f3"
DRAFT_ONLY = "SENTINEL-DRAFT-4c1"


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="sa-east-1")
        table = ddb.create_table(
            TableName="resume",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="sa-east-1")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "sa-east-1"})
        yield table, s3


@pytest.fixture
def store(aws):
    table, s3 = aws
    s = Store(table, s3, BUCKET, KEY)
    s.seed(MASTER)
    return s


def s3_body(aws):
    return aws[1].get_object(Bucket=BUCKET, Key=KEY)["Body"].read()


def edited(master: Master, text: str) -> Master:
    m = master.model_copy(deep=True)
    m.entries.append(Entry(id="x-new", kind="highlight", text=text))
    return m


def test_seed_sets_draft_and_live_to_version_1_and_is_idempotent(store):
    assert store.get_live() == (MASTER, 1)
    assert store.get_draft() == (MASTER, 1)
    store.seed(edited(MASTER, "other"))  # already seeded: no-op
    assert store.get_live()[0] == MASTER


def test_save_draft_bumps_version_and_leaves_live_alone(store):
    v = store.save_draft(edited(MASTER, "hello"), expected_version=1)
    assert v == 2
    assert store.get_draft()[1] == 2
    assert store.get_live() == (MASTER, 1)


def test_save_draft_with_stale_version_conflicts(store):
    store.save_draft(edited(MASTER, "a"), expected_version=1)
    with pytest.raises(Conflict):
        store.save_draft(edited(MASTER, "b"), expected_version=1)


def test_publish_requires_the_current_draft_version(store, aws):
    v = store.save_draft(edited(MASTER, "a"), expected_version=1)
    with pytest.raises(Conflict):
        store.publish(draft_version=v - 1)
    with pytest.raises(ClientError):
        aws[1].get_object(Bucket=BUCKET, Key=KEY)  # nothing was written
    assert store.get_live()[1] == 1


def test_publish_promotes_draft_and_writes_the_public_snapshot(store, aws):
    draft = edited(MASTER, "fresh bullet")
    v = store.save_draft(draft, expected_version=1)
    assert store.publish(draft_version=v) == 2
    assert store.get_live() == (draft, 2)
    obj = aws[1].get_object(Bucket=BUCKET, Key=KEY)
    assert obj["Body"].read() == snapshot.render(draft)
    assert obj["CacheControl"] == "no-cache"
    assert obj["ContentType"].startswith("application/json")


def test_second_publish_of_the_same_draft_conflicts(store):
    v = store.save_draft(edited(MASTER, "a"), expected_version=1)
    store.publish(draft_version=v)
    with pytest.raises(Conflict):
        store.publish(draft_version=v)


def test_private_and_draft_entries_never_reach_the_snapshot(store, aws):
    m = MASTER.model_copy(deep=True)
    m.entries.append(Entry(id="x-priv", kind="highlight", visibility="private", text=SECRET))
    m.entries.append(Entry(id="x-draft", kind="highlight", status="draft", text=DRAFT_ONLY))
    store.publish(draft_version=store.save_draft(m, expected_version=1))
    body = s3_body(aws).decode()
    assert SECRET not in body and DRAFT_ONLY not in body
    assert json.loads(body) == project(m)


def test_history_lists_replaced_live_versions_and_rollback_restores_into_the_draft(store):
    store.publish(draft_version=store.save_draft(edited(MASTER, "v2"), expected_version=1))
    store.publish(draft_version=store.save_draft(edited(MASTER, "v3"), expected_version=store.get_draft()[1]))
    assert store.history() == [2, 1]  # newest first; version 3 is live
    dv = store.rollback(1)
    assert store.get_draft() == (MASTER, dv)
    assert store.get_live()[1] == 3  # rollback only touches the draft until published


def test_rollback_to_an_unknown_version_fails(store):
    with pytest.raises(KeyError):
        store.rollback(99)


def test_discard_draft_resets_it_to_live(store):
    store.save_draft(edited(MASTER, "junk"), expected_version=1)
    store.discard_draft()
    assert store.get_draft()[0] == MASTER


def test_publish_error_from_s3_propagates(aws):
    table, s3 = aws
    s = Store(table, s3, "no-such-bucket", KEY)
    s.seed(MASTER)
    v = s.save_draft(edited(MASTER, "a"), expected_version=1)
    with pytest.raises(ClientError):
        s.publish(draft_version=v)
    # LIVE is ahead of the snapshot now; resync heals it without a new publish
    s.bucket = BUCKET
    s.resync_snapshot()
    assert s3.get_object(Bucket=BUCKET, Key=KEY)["Body"].read() == snapshot.render(s.get_live()[0])
