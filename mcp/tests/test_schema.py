"""Master CV schema, public projection and seed. The golden test is the key guard: the master must reproduce
today's general CV (lib/cv.json) exactly, and the role variants' wording must survive as non-general entries."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resume_mcp.project import project
from resume_mcp.schema import Master
from resume_mcp.seed import build_master

ROOT = Path(__file__).resolve().parents[2]
CV = json.loads((ROOT / "lib" / "cv.json").read_text())
LEGACY = {
    p.stem.removeprefix("cv."): json.loads(p.read_text()) for p in sorted((ROOT / "data" / "legacy").glob("cv.*.json"))
}


def canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


# ---- golden + legacy ------------------------------------------------------------------------------------------


def test_projecting_the_seeded_master_reproduces_the_general_cv_exactly():
    assert project(build_master(CV, LEGACY)) == CV


def test_legacy_wording_survives_as_non_general_entries_tagged_with_their_role():
    m = build_master(CV, LEGACY)
    by_text = {}
    for e in m.entries:
        if e.text is not None:
            by_text.setdefault(canon(e.text), []).append(e)
    assert LEGACY, "data/legacy variants must exist"
    for role, cv in LEGACY.items():
        texts = [h for w in cv["work"] for h in w["highlights"]] + cv["profile"]
        for text in texts:
            hits = by_text.get(canon(text), [])
            assert hits, f"{role}: lost bullet {text!r}"
            assert any(e.general or role in e.roles for e in hits), f"{role}: bullet not tagged {text!r}"


def test_non_general_entries_never_reach_the_projection():
    m = build_master(CV, LEGACY)
    assert any(not e.general for e in m.entries)
    out = project(m)
    assert sum(len(w["highlights"]) for w in out["work"]) == sum(len(w["highlights"]) for w in CV["work"])


def test_committed_master_json_is_valid_and_in_sync_with_the_seed():
    committed = json.loads((ROOT / "data" / "master.json").read_text())
    assert Master.model_validate(committed).model_dump(mode="json") == build_master(CV, LEGACY).model_dump(mode="json")


# ---- validation -----------------------------------------------------------------------------------------------


def entry(id, kind="profile", text="hello", **kw):
    return {"id": id, "kind": kind, "text": text, "general": True, "order": 0, **kw}


def master(*entries, tags=("python",)):
    return {
        "version": 1,
        "basics": {
            "name": "N",
            "label": "L",
            "email": "e@x.y",
            "phone": "1",
            "location": "Z",
            "profiles": [],
        },
        "tag_vocab": list(tags),
        "entries": list(entries),
    }


def test_a_minimal_master_validates():
    Master.model_validate(master(entry("a"), entry("b", text={"en": "x", "pt": "y"})))


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(master(entry("a", text={"en": "only english"})), id="missing pt"),
        pytest.param(master(entry("a", text={"en": "x", "pt": ""})), id="empty pt"),
        pytest.param(master(entry("a", kind="mystery")), id="unknown kind"),
        pytest.param(master(entry("a", tags=["rust"])), id="unknown tag"),
        pytest.param(master(entry("a"), entry("a")), id="duplicate id"),
        pytest.param(master(entry("a", kind="highlight", parent="nope")), id="dangling parent"),
        pytest.param(master(entry("a", status="published")), id="bad status"),
        pytest.param(master(entry("a", visibility="secret")), id="bad visibility"),
        pytest.param(master(entry("a", text="<script>alert(1)</script>")), id="script tag"),
        pytest.param(master(entry("a", text="<strong onclick=x>hi</strong>")), id="attribute on allowed tag"),
        pytest.param(master(entry("a", text={"en": "ok", "pt": "<img src=x>"})), id="img tag in pt"),
    ],
)
def test_invalid_masters_are_rejected(bad):
    with pytest.raises(ValidationError):
        Master.model_validate(bad)


def test_bare_inline_formatting_tags_are_allowed():
    Master.model_validate(master(entry("a", text="a <strong>b</strong> <em>c</em> <b>d</b> <i>e</i>")))


# ---- public projection ----------------------------------------------------------------------------------------


def sentinel_master():
    return Master.model_validate(
        master(
            entry("p1", text="PUBLIC-PROFILE"),
            entry("p2", text="SECRET-PRIVATE-PROFILE", visibility="private"),
            entry("p3", text="SECRET-DRAFT-PROFILE", status="draft"),
            entry("p4", text="PUBLIC-WITH-NOTES", notes="SECRET-NOTES"),
            entry("p5", text="SECRET-NONGENERAL", general=False, roles=["backend"]),
            entry(
                "w1",
                kind="work",
                text=None,
                meta={
                    "company": "Acme",
                    "position": "Dev",
                    "startDate": "2020-01",
                    "endDate": None,
                    "technologies": ["python"],
                    "internal_flag": "SECRET-META",
                },
            ),
            entry("h1", kind="highlight", parent="w1", text="PUBLIC-HIGHLIGHT"),
            entry("h2", kind="highlight", parent="w1", text="SECRET-PRIVATE-HIGHLIGHT", visibility="private"),
            entry("h3", kind="highlight", parent="w1", text="SECRET-DRAFT-HIGHLIGHT", status="draft"),
            entry("w2", kind="work", text=None, visibility="private", meta={"company": "SECRET-COMPANY"}),
            entry("h4", kind="highlight", parent="w2", text="SECRET-UNDER-PRIVATE-PARENT"),
        )
    )


def test_projection_never_leaks_private_draft_notes_non_general_or_unknown_keys():
    out = json.dumps(project(sentinel_master()), ensure_ascii=False)
    assert "SECRET" not in out
    for ok in ("PUBLIC-PROFILE", "PUBLIC-WITH-NOTES", "PUBLIC-HIGHLIGHT", "Acme"):
        assert ok in out


def test_projection_has_a_stable_shape_even_when_sections_are_empty():
    out = project(sentinel_master())
    assert set(out) == {"basics", "profile", "work", "education", "projects", "courses", "skills", "languages"}
    assert out["courses"] == [] and out["skills"] == [] and out["languages"] == []
    assert [w["company"] for w in out["work"]] == ["Acme"]
    assert out["work"][0]["highlights"] == ["PUBLIC-HIGHLIGHT"]


def test_projection_orders_by_order_field_and_does_not_mutate_the_master():
    m = Master.model_validate(
        master(entry("b", text="second", order=2), entry("a", text="first", order=1), entry("c", text="third", order=3))
    )
    before = copy.deepcopy(m.model_dump(mode="json"))
    assert project(m)["profile"] == ["first", "second", "third"]
    assert m.model_dump(mode="json") == before
