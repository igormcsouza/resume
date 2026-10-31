import json
from pathlib import Path

from resume_mcp import snapshot
from resume_mcp.project import project
from resume_mcp.schema import Master

MASTER = Master.model_validate_json((Path(__file__).parents[2] / "data" / "master.json").read_text())


def test_render_is_the_public_projection_as_utf8_json():
    body = snapshot.render(MASTER)
    assert isinstance(body, bytes)
    assert json.loads(body) == project(MASTER)


def test_render_is_deterministic_and_keeps_unicode():
    assert snapshot.render(MASTER) == snapshot.render(MASTER.model_copy(deep=True))
    assert "\\u00" not in snapshot.render(MASTER).decode()  # accents stay readable, not escaped


def test_render_does_not_mutate_the_master():
    before = MASTER.model_dump_json()
    snapshot.render(MASTER)
    assert MASTER.model_dump_json() == before
