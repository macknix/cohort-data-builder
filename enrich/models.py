"""The shape the LLM must answer in, built from the schema.

Topic ids are a Literal of exactly the schema's ids. That one type does two
jobs: its JSON schema is handed to Ollama as the output format, so decoding
is constrained to real topic ids, and the PydanticOutputParser rejects
anything that slips through anyway.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, create_model

from .schema import Schema


def output_model(schema: Schema) -> type[BaseModel]:
    """BatchTags for this schema:

        {"variables": [{"id": 0, "topics": [{"topic": "smoking", "confidence": 0.9}]}]}
    """
    topic_id = Literal[tuple(schema.topics)]  # type: ignore[valid-type]

    TopicScore = create_model(
        "TopicScore",
        topic=(topic_id, Field(description="A topic id from the list")),
        confidence=(float, Field(ge=0, le=1, description="How sure, from 0 to 1")),
    )
    VariableTags = create_model(
        "VariableTags",
        id=(int, Field(description="The variable's id, as given")),
        topics=(list[TopicScore], Field(min_length=1)),
    )
    return create_model(
        "BatchTags",
        variables=(list[VariableTags], Field(description="One entry per variable given")),
    )


def tidy(topics: list) -> dict[str, float]:
    """One confidence per topic (the highest, if the model repeated one),
    rounded, highest first."""
    best: dict[str, float] = {}
    for t in topics:
        best[t.topic] = max(best.get(t.topic, 0.0), float(t.confidence))
    return {k: round(v, 3) for k, v in sorted(best.items(), key=lambda kv: -kv[1])}
