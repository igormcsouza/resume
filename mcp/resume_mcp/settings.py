import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    issuer: str  # Citadel (the SSO user pool) issuer
    client_id: str  # this app's client in Citadel
    hosted_ui: str  # Citadel login domain
    owner_subs: frozenset[str]  # Citadel users allowed to approve a connector
    resource_url: str = ""
    public_url: str = ""  # the public origin when a CDN fronts the API (its Host is not ours)
    table_name: str = ""
    bucket_name: str = ""
    snapshot_key: str = "cv.json"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            issuer=e["ISSUER"],
            client_id=e["CLIENT_ID"],
            hosted_ui=e["HOSTED_UI"].rstrip("/"),
            owner_subs=frozenset(s.strip() for s in e["OWNER_SUBS"].split(",") if s.strip()),
            resource_url=e.get("RESOURCE_URL", ""),
            public_url=e.get("PUBLIC_URL", "").rstrip("/"),
            table_name=e.get("TABLE_NAME", ""),
            bucket_name=e.get("BUCKET_NAME", ""),
            snapshot_key=e.get("SNAPSHOT_KEY", "cv.json"),
        )
