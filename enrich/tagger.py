"""Asking the model to tag one batch of variables.

The prompt carries the schema's guidance and topics and the parser's format
instructions; the variables go in as one JSON object per line, each with a
batch-local id. The reply is parsed by LangChain's PydanticOutputParser into
the model built from the schema (models.py), so every topic id and every
confidence is checked before anything is stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser

from .corpus import Variable
from .models import output_model, tidy
from .schema import Schema

SYSTEM = """{guidance}

# Topics
{topics}

# Output
Return one entry for EVERY variable you are given, using its id. Each entry
lists the topics that apply, each with a confidence between 0 and 1.

{format_instructions}"""

USER = """Dataset: {dataset}

Variables, one JSON object per line:
{variables}"""


@dataclass
class BatchResult:
    tags: dict[int, dict[str, float]]     # batch id -> {topic: confidence}
    missing: list[int]                    # ids the model did not answer for


class Tagger:
    def __init__(self, schema: Schema, llm, dataset_name: str):
        """`llm` is anything with .invoke(messages) returning a message with
        .content: a ChatOllama in use, a stub in tests."""
        self.schema = schema
        self.model = output_model(schema)
        self.parser = PydanticOutputParser(pydantic_object=self.model)
        self.llm = llm
        self.dataset_name = dataset_name
        self.system = SYSTEM.format(
            guidance=schema.guidance.strip(),
            topics=schema.prompt_text(),
            format_instructions=self.parser.get_format_instructions(),
        )

    def messages(self, batch: list[Variable]) -> list:
        lines = "\n".join(json.dumps(v.for_prompt(i), ensure_ascii=False)
                          for i, v in enumerate(batch))
        return [SystemMessage(self.system),
                HumanMessage(USER.format(dataset=self.dataset_name, variables=lines))]

    def tag(self, batch: list[Variable]) -> BatchResult:
        """Raises OutputParserException if the reply does not parse, and lets
        connection errors through: the caller decides whether to retry."""
        reply = self.llm.invoke(self.messages(batch))
        parsed = self.parser.parse(reply.content)
        tags = {}
        for v in parsed.variables:
            if 0 <= v.id < len(batch) and v.id not in tags:
                tags[v.id] = tidy(v.topics)
        return BatchResult(tags=tags, missing=[i for i in range(len(batch)) if i not in tags])


def ollama(model: str, base_url: str, schema: Schema, temperature: float,
           num_ctx: int, reasoning: str | None, timeout: float):
    """A ChatOllama held to the output model's JSON schema.

    `format` makes Ollama constrain decoding to that schema, so a topic id
    outside the list cannot be produced; the parser still checks the result.
    """
    from langchain_ollama import ChatOllama

    kwargs = {}
    if reasoning is not None:
        kwargs["reasoning"] = {"true": True, "false": False}.get(reasoning, reasoning)
    return ChatOllama(
        model=model, base_url=base_url, temperature=temperature, num_ctx=num_ctx,
        format=output_model(schema).model_json_schema(),
        client_kwargs={"timeout": timeout}, **kwargs,
    )
