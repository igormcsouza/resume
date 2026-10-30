"""Public projection: master -> the exact shape of lib/cv.json. A whitelist, so nothing private can slip in."""

from typing import Any

from .schema import Entry, Master

_META = {
    "work": ("company", "url", "position", "startDate", "endDate", "technologies"),
    "education": ("institution", "startDate", "endDate"),
    "project": ("name", "stack"),
    "skill": ("category", "items"),
    "language": ("name", "level"),
}


def _pick(e: Entry) -> dict[str, Any]:
    return {k: e.meta[k] for k in _META.get(e.kind, ()) if k in e.meta}


def project(master: Master) -> dict[str, Any]:
    def shown(e: Entry) -> bool:
        return e.status == "live" and e.visibility == "public" and e.general

    parents = {e.id for e in master.entries if shown(e)}
    visible = sorted(
        (e for e in master.entries if shown(e) and (e.parent is None or e.parent in parents)),
        key=lambda e: e.order,  # sorted() is stable
    )

    def of(kind: str) -> list[Entry]:
        return [e for e in visible if e.kind == kind]

    return {
        "basics": master.basics.model_dump(),
        "profile": [e.text for e in of("profile")],
        "work": [
            {**_pick(w), "highlights": [h.text for h in of("highlight") if h.parent == w.id]} for w in of("work")
        ],
        "education": [{**_pick(e), "degree": e.text} for e in of("education")],
        "projects": [{**_pick(e), "description": e.text} for e in of("project")],
        "courses": [e.text for e in of("course")],
        "skills": [_pick(e) for e in of("skill")],
        "languages": [_pick(e) for e in of("language")],
    }
