"""Seed the store from data/master.json and publish the first snapshot: python -m resume_mcp.load."""

import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from .schema import Master
from .store import Store


def load(store: Store, master: Master) -> None:
    store.seed(master)
    try:
        store.s3.head_object(Bucket=store.bucket, Key=store.key)
    except ClientError:  # ponytail: any head failure (404/403) means "write it"; a real outage fails on the write
        store.resync_snapshot()


def main() -> None:
    master = Master.model_validate_json((Path(__file__).resolve().parents[2] / "data" / "master.json").read_text())
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    key = os.environ.get("SNAPSHOT_KEY", "cv.json")
    load(Store(table, boto3.client("s3"), os.environ["BUCKET_NAME"], key), master)


if __name__ == "__main__":
    main()
