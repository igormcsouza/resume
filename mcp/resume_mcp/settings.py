import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    issuer: str
    client_id: str
    resource_url: str
    hosted_ui: str
    as_mode: str = "cognito"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            issuer=e["ISSUER"],
            client_id=e["CLIENT_ID"],
            hosted_ui=e["HOSTED_UI"],
            resource_url=e.get("RESOURCE_URL", ""),
            as_mode=e.get("AS_MODE", "cognito"),
        )
