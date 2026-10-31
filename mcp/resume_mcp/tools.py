"""Owner tools over the Store: read (public CV, master, search) and write-to-draft (add, update, publish, history)."""

from .project import project
from .schema import Entry, Master


def get_cv(store) -> dict:
    live, version = store.get_live()
    return {"version": version, "cv": project(live)}


def get_master(store) -> dict:
    draft, dv = store.get_draft()
    return {"draft_version": dv, "live_version": store.get_live()[1], "master": draft.model_dump()}


def _texts(e: Entry) -> list[str]:
    if isinstance(e.text, dict):
        return list(e.text.values())
    return [e.text] if e.text else []


def search_experience(store, query: str, limit: int = 20) -> list[dict]:
    q = query.lower()
    out = []
    for e in store.get_draft()[0].entries:
        texts = _texts(e)
        if any(q in s.lower() for s in [*texts, *e.tags, *(str(v) for v in e.meta.values())]):
            out.append({"id": e.id, "kind": e.kind, "parent": e.parent, "text": " / ".join(texts), "tags": e.tags})
    return out[:limit]


def _save(store, draft: Master, entries: list[Entry], version: int) -> dict:
    # model_validate re-runs the cross-field checks (duplicate id, parent, tag vocab)
    master = Master.model_validate({**draft.model_dump(), "entries": [e.model_dump() for e in entries]})
    return {"draft_version": store.save_draft(master, version)}


def add_entry(store, entry: dict) -> dict:
    draft, version = store.get_draft()
    return _save(store, draft, [*draft.entries, Entry.model_validate(entry)], version)


def update_entry(store, id: str, fields: dict) -> dict:
    if {"id", "kind"} & set(fields):
        raise ValueError("id and kind cannot be changed")
    if unknown := set(fields) - set(Entry.model_fields):
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    draft, version = store.get_draft()
    if id not in {e.id for e in draft.entries}:
        raise KeyError(id)
    entries = [Entry.model_validate({**e.model_dump(), **fields}) if e.id == id else e for e in draft.entries]
    return _save(store, draft, entries, version)


def publish(store, draft_version: int) -> dict:
    return {"live_version": store.publish(draft_version)}


def discard_draft(store) -> dict:
    return {"draft_version": store.discard_draft()}


def history(store) -> dict:
    return {"live_version": store.get_live()[1], "previous_versions": store.history()}


def rollback(store, version: int) -> dict:
    return {"draft_version": store.rollback(version)}


def resync_snapshot(store) -> dict:
    store.resync_snapshot()
    return {"ok": True}
