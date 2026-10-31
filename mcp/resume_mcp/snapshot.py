"""Public snapshot: the bytes published to S3 for the site to fetch."""

import json

from .project import project
from .schema import Master


def render(master: Master) -> bytes:
    return json.dumps(project(master), sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
