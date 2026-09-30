"""The topic schema: loading schema/topics.yaml and checking it.

The YAML is the one place topics are defined. Everything else - the prompt,
the output model the LLM is held to, the snapshot the site reads - is derived
from what is loaded here.
"""

from __future__ import annotations

import hashlib
import re
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = r"^[a-z][a-z0-9_]*$"


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID)
    label: str
    description: str
    closer: str | None = None
    added: bool = False


class Domain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID)
    label: str
    description: str = ""
    closer: str | None = None
    cessda: str | None = None
    topics: list[Topic] = Field(min_length=1)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    name: str
    guidance: str = ""
    domains: list[Domain] = Field(min_length=1)
    # The file's own hash, set by load(): what "these tags are current" means.
    hash: str = ""

    @model_validator(mode="after")
    def ids_are_unique(self) -> "Schema":
        seen: set[str] = set()
        for d in self.domains:
            for i in [d.id, *(t.id for t in d.topics)]:
                if i in seen:
                    raise ValueError(f'id "{i}" is used twice; every domain and topic id must be unique')
                seen.add(i)
        return self

    @cached_property
    def topics(self) -> dict[str, Topic]:
        return {t.id: t for d in self.domains for t in d.topics}

    @cached_property
    def domain_of(self) -> dict[str, Domain]:
        return {t.id: d for d in self.domains for t in d.topics}

    def prompt_text(self) -> str:
        """The topics as the model reads them: grouped by domain, one per line."""
        lines = []
        for d in self.domains:
            lines.append(f"\n## {d.label}" + (f" — {d.description}" if d.description else ""))
            for t in d.topics:
                lines.append(f"- {t.id}: {t.label}. {t.description}")
        return "\n".join(lines).strip()

    def snapshot(self) -> dict:
        """What the site needs to draw the tags, as plain JSON.

        Written next to the tags so build.py can read it with the standard
        library, without YAML, and so tags always travel with the schema that
        made them.
        """
        return {
            "version": self.version,
            "name": self.name,
            "hash": self.hash,
            "domains": [
                {"id": d.id, "label": d.label, "description": d.description,
                 "topics": [{"id": t.id, "label": t.label, "description": t.description}
                            for t in d.topics]}
                for d in self.domains
            ],
        }


def load(path: Path) -> Schema:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    data["hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return Schema.model_validate(data)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
