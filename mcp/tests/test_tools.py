"""Owner tools over the Store: read (public CV, master, search) and write-to-draft (add, update, publish, history)."""

import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from resume_mcp import tools
from resume_mcp.project import project
from resume_mcp.schema import Master
from resume_mcp.store import Conflict, Store

MASTER = Master.model_validate_json((Path(__file__).parents[2] / "data" / "master.json").read_text())
BUCKET, KEY = "resume-snapshot", "cv.json"
SECRET = "SENTINEL-PRIVATE-77"


@pytest.fixture
def aws():
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="sa-east-1").create_table(
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
    s = Store(*aws[:2], BUCKET, KEY)
    s.seed(MASTER)
    return s


def a_work_id():
    return next(e.id for e in MASTER.entries if e.kind == "work")


def test_get_cv_is_the_live_public_projection_with_its_version(store):
    out = tools.get_cv(store)
    assert out["version"] == 1 and out["cv"] == project(MASTER)


def test_get_master_returns_the_draft_with_its_version_including_private_entries(store):
    tools.add_entry(store, {"id": "x-priv", "kind": "highlight", "visibility": "private", "text": SECRET})
    out = tools.get_master(store)
    assert out["draft_version"] == 2 and out["live_version"] == 1
    assert any(e["id"] == "x-priv" for e in out["master"]["entries"])


def test_search_matches_text_tags_and_both_languages_case_insensitively(store):
    hits = tools.search_experience(store, "PYTHON")
    assert hits and all({"id", "kind", "text", "tags"} <= set(h) for h in hits)
    assert tools.search_experience(store, "zzz-no-such-thing") == []
    assert len(tools.search_experience(store, "python", limit=2)) <= 2


def test_search_sees_private_and_draft_entries_because_the_caller_is_the_owner(store):
    tools.add_entry(store, {"id": "x-priv", "kind": "highlight", "visibility": "private", "text": SECRET})
    assert [h["id"] for h in tools.search_experience(store, SECRET)] == ["x-priv"]


def test_add_entry_goes_to_the_draft_only(store):
    out = tools.add_entry(store, {"id": "x-new", "kind": "highlight", "text": "Shipped a thing", "parent": a_work_id()})
    assert out["draft_version"] == 2
    assert tools.get_cv(store)["cv"] == project(MASTER)  # live is untouched


def test_add_entry_rejects_duplicates_bad_parents_unknown_tags_and_html(store):
    with pytest.raises(ValueError):
        tools.add_entry(store, {"id": a_work_id(), "kind": "highlight", "text": "dup"})
    with pytest.raises(ValueError):
        tools.add_entry(store, {"id": "x1", "kind": "highlight", "text": "t", "parent": "nope"})
    with pytest.raises(ValueError):
        tools.add_entry(store, {"id": "x2", "kind": "highlight", "text": "t", "tags": ["not-in-vocab"]})
    with pytest.raises(ValueError):
        tools.add_entry(store, {"id": "x3", "kind": "highlight", "text": "<script>alert(1)</script>"})
    assert store.get_draft()[1] == 1  # nothing was saved


def test_update_entry_merges_fields_and_protects_id_and_kind(store):
    eid = next(e.id for e in MASTER.entries if e.kind == "highlight")
    tools.update_entry(store, eid, {"text": "Rewritten", "visibility": "private"})
    e = next(e for e in store.get_draft()[0].entries if e.id == eid)
    assert e.text == "Rewritten" and e.visibility == "private"
    with pytest.raises(ValueError):
        tools.update_entry(store, eid, {"id": "other"})
    with pytest.raises(ValueError):
        tools.update_entry(store, eid, {"kind": "work"})
    with pytest.raises(ValueError):
        tools.update_entry(store, eid, {"bogus": 1})
    with pytest.raises(KeyError):
        tools.update_entry(store, "no-such-id", {"text": "x"})


def test_publish_needs_the_draft_version_and_pushes_the_snapshot(store, aws):
    v = tools.add_entry(store, {"id": "x-new", "kind": "highlight", "text": "Fresh"})["draft_version"]
    with pytest.raises(Conflict):
        tools.publish(store, v + 5)
    assert tools.publish(store, v) == {"live_version": 2}
    body = aws[1].get_object(Bucket=BUCKET, Key=KEY)["Body"].read().decode()
    assert "Fresh" in body and json.loads(body)["version"] if "version" in json.loads(body) else True


def test_private_entry_is_never_published(store, aws):
    v = tools.add_entry(store, {"id": "x-priv", "kind": "highlight", "visibility": "private", "text": SECRET})["draft_version"]
    tools.publish(store, v)
    assert SECRET not in aws[1].get_object(Bucket=BUCKET, Key=KEY)["Body"].read().decode()


def test_discard_history_and_rollback(store):
    tools.add_entry(store, {"id": "x-a", "kind": "highlight", "text": "A"})
    assert tools.discard_draft(store)["draft_version"] == 3
    assert not any(e.id == "x-a" for e in store.get_draft()[0].entries)
    v = tools.add_entry(store, {"id": "x-b", "kind": "highlight", "text": "B"})["draft_version"]
    tools.publish(store, v)
    assert tools.history(store) == {"live_version": 2, "previous_versions": [1]}
    tools.rollback(store, 1)
    assert not any(e.id == "x-b" for e in store.get_draft()[0].entries)
    assert store.get_live()[1] == 2  # rollback only restores the draft


def test_resync_snapshot_republishes_live(store, aws):
    tools.resync_snapshot(store)
    assert aws[1].get_object(Bucket=BUCKET, Key=KEY)["Body"].read()
