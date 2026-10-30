"""Build data/master.json from the general CV (lib/cv.json) plus the legacy role variants (data/legacy)."""

import json
from pathlib import Path
from typing import Any

from .schema import Entry, Master

ROOT = Path(__file__).resolve().parents[2]


def canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def build_master(cv: dict, legacy: dict[str, dict]) -> Master:
    entries: list[Entry] = []

    def add(**kw: Any) -> Entry:
        entries.append(Entry(**kw))
        return entries[-1]

    for i, t in enumerate(cv["profile"]):
        add(id=f"profile-{i}", kind="profile", text=t, order=i)
    work_ids: dict[str, str] = {}
    for i, w in enumerate(cv["work"]):
        wid = work_ids[w["company"]] = f"work-{i}"
        tags = sorted({t.lower() for t in w.get("technologies", [])})
        add(id=wid, kind="work", tags=tags, meta={k: v for k, v in w.items() if k != "highlights"}, order=i)
        for j, h in enumerate(w["highlights"]):
            add(id=f"{wid}-h{j}", kind="highlight", parent=wid, text=h, order=j)
    for i, e in enumerate(cv["education"]):
        meta = {k: v for k, v in e.items() if k != "degree"}
        add(id=f"education-{i}", kind="education", text=e["degree"], meta=meta, order=i)
    for i, p in enumerate(cv["projects"]):
        meta = {k: v for k, v in p.items() if k != "description"}
        add(id=f"project-{i}", kind="project", text=p["description"], meta=meta, order=i)
    for i, c in enumerate(cv["courses"]):
        add(id=f"course-{i}", kind="course", text=c, order=i)
    for i, s in enumerate(cv["skills"]):
        add(id=f"skill-{i}", kind="skill", meta=s, order=i)
    for i, lang in enumerate(cv["languages"]):
        add(id=f"language-{i}", kind="language", meta=lang, order=i)

    existing = {(e.parent, canon(e.text)) for e in entries}
    extra: dict[tuple, Entry] = {}
    for role in sorted(legacy):
        cvr = legacy[role]
        items = [(None, "profile", t) for t in cvr["profile"]]
        items += [(work_ids[w["company"]], "highlight", h) for w in cvr["work"] for h in w["highlights"]]
        for parent, kind, text in items:
            key = (parent, canon(text))
            if key in existing:
                continue
            if key in extra:
                if role not in extra[key].roles:
                    extra[key].roles.append(role)
                continue
            n = len(extra)
            extra[key] = add(
                id=f"legacy-{n}", kind=kind, parent=parent, text=text, general=False, roles=[role], order=1000 + n
            )

    vocab = sorted({t for e in entries for t in e.tags} | set(legacy))
    return Master(basics=cv["basics"], tag_vocab=vocab, entries=entries)


def main() -> None:
    cv = json.loads((ROOT / "lib" / "cv.json").read_text())
    legacy = {
        p.stem.removeprefix("cv."): json.loads(p.read_text())
        for p in sorted((ROOT / "data" / "legacy").glob("cv.*.json"))
    }
    out = build_master(cv, legacy).model_dump(mode="json")
    (ROOT / "data" / "master.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
