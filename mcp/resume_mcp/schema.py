"""Master CV model: one list of entries, each flagged for visibility, so private data can't leak by omission."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Text = str | dict[str, str]
# Only bare inline formatting tags survive; any other angle bracket is rejected.
_ALLOWED_TAGS = re.compile(r"</?(?:strong|b|em|i)>")


def _check_string(s: object) -> None:
    if not isinstance(s, str) or not s.strip():
        raise ValueError("text must be a non-empty string")
    rest = _ALLOWED_TAGS.sub("", s)
    if "<" in rest or ">" in rest:
        raise ValueError("only bare <strong>, <b>, <em>, <i> tags are allowed")


class Basics(BaseModel):
    name: str
    label: Any
    email: str
    phone: str
    location: Any
    profiles: list[dict]


class Entry(BaseModel):
    id: str
    kind: Literal["profile", "work", "highlight", "education", "project", "course", "skill", "language"]
    status: Literal["live", "draft"] = "live"
    visibility: Literal["public", "private"] = "public"
    general: bool = True
    tags: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    text: Text | None = None
    parent: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    order: int = 0
    notes: str | None = None

    @field_validator("text")
    @classmethod
    def _text(cls, v: Text | None) -> Text | None:
        if isinstance(v, dict):
            if set(v) != {"en", "pt"}:
                raise ValueError("text dict needs exactly en and pt")
            for s in v.values():
                _check_string(s)
        elif v is not None:
            _check_string(v)
        return v


class Master(BaseModel):
    version: int = 1
    basics: Basics
    tag_vocab: list[str] = Field(default_factory=list)
    entries: list[Entry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "Master":
        ids = [e.id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate entry id")
        vocab = set(self.tag_vocab)
        for e in self.entries:
            if e.parent is not None and e.parent not in ids:
                raise ValueError(f"{e.id}: unknown parent {e.parent}")
            if not set(e.tags) <= vocab:
                raise ValueError(f"{e.id}: tag not in tag_vocab")
        return self
