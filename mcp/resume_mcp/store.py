"""DynamoDB-backed master store (DRAFT, LIVE, HIST#<version>) plus the public S3 snapshot, with optimistic versions."""

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from . import snapshot
from .schema import Master

PK = "MASTER"


class Conflict(Exception):
    """The caller's version is stale, or there is nothing to publish."""


class Store:
    def __init__(self, table, s3, bucket: str, key: str = "cv.json"):
        self.table, self.s3, self.bucket, self.key = table, s3, bucket, key

    def _item(self, sk: str) -> dict | None:
        return self.table.get_item(Key={"pk": PK, "sk": sk}, ConsistentRead=True).get("Item")

    def _put(self, sk: str, master: str, version: int, expected: int | None = None) -> None:
        """Write an item; if `expected` is given, only when the stored version still equals it."""
        kwargs = {}
        if expected is not None:
            kwargs["ConditionExpression"] = Attr("version").eq(expected)
        try:
            self.table.put_item(Item={"pk": PK, "sk": sk, "version": version, "master": master}, **kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            raise Conflict(f"{sk} changed concurrently") from e

    def _get(self, sk: str) -> tuple[Master, int]:
        item = self._item(sk)
        return Master.model_validate_json(item["master"]), int(item["version"])

    def seed(self, master: Master) -> None:
        if self._item("LIVE"):
            return
        body = master.model_dump_json()
        self._put("DRAFT", body, 1)
        self._put("LIVE", body, 1)

    def get_live(self) -> tuple[Master, int]:
        return self._get("LIVE")

    def get_draft(self) -> tuple[Master, int]:
        return self._get("DRAFT")

    def save_draft(self, master: Master, expected_version: int) -> int:
        self._put("DRAFT", master.model_dump_json(), expected_version + 1, expected=expected_version)
        return expected_version + 1

    def publish(self, draft_version: int) -> int:
        draft, dv = self.get_draft()
        live, lv = self.get_live()
        if dv != draft_version:
            raise Conflict("draft changed since it was read")
        if draft == live:
            raise Conflict("nothing to publish")
        self._put(f"HIST#{lv:08d}", live.model_dump_json(), lv)
        self._put("LIVE", draft.model_dump_json(), lv + 1, expected=lv)
        # S3 last: a failed upload leaves LIVE ahead of the snapshot.
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=snapshot.render(draft),
            ContentType="application/json",
            CacheControl="no-cache",
        )
        return lv + 1

    def history(self) -> list[int]:
        res = self.table.query(
            KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with("HIST#"), ScanIndexForward=False
        )
        return [int(i["version"]) for i in res["Items"]]

    def rollback(self, version: int) -> int:
        item = self._item(f"HIST#{version:08d}")
        if item is None:
            raise KeyError(version)
        return self._reset_draft(item["master"])

    def discard_draft(self) -> int:
        return self._reset_draft(self._item("LIVE")["master"])

    def _reset_draft(self, master_json: str) -> int:
        _, dv = self.get_draft()
        self._put("DRAFT", master_json, dv + 1, expected=dv)
        return dv + 1
