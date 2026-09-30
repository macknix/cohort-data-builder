"""The tagging pipeline, with a stub in place of the model. Needs the project's
dependencies (uv sync), not Ollama."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("pydantic", "yaml", "langchain_core", "rich"))

if HAVE_DEPS:
    from pydantic import ValidationError
    from enrich import cli, corpus, models
    from enrich import schema as schema_mod
    from enrich.corpus import Variable
    from enrich.store import TagStore
    from enrich.tagger import Tagger

SCHEMA = ROOT / "schema" / "topics.yaml"


class Reply:
    def __init__(self, content: str):
        self.content = content


class StubLLM:
    """Answers each request from a queue of replies (str, or an exception)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply)


def var(name: str, label: str = "a label") -> "Variable":
    return Variable(file="f", name=name, label=label, wave="1y", wave_label="",
                    file_description="", level="NOMINAL")


def answer(*entries) -> str:
    return json.dumps({"variables": [
        {"id": i, "topics": [{"topic": t, "confidence": c} for t, c in topics]}
        for i, topics in entries]})


@unittest.skipUnless(HAVE_DEPS, "run `uv sync` for the pipeline's dependencies")
class Schema(unittest.TestCase):
    def test_the_committed_schema_loads(self):
        s = schema_mod.load(SCHEMA)
        self.assertGreater(len(s.topics), 50)
        self.assertIn("smoking", s.topics)
        self.assertEqual(s.domain_of["smoking"].id, "health_behaviour")
        self.assertEqual(len(s.hash), 12)

    def test_duplicate_ids_are_refused(self):
        text = SCHEMA.read_text().replace("id: sleep", "id: smoking")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(text)
            with self.assertRaises(ValidationError):
                schema_mod.load(path)

    def test_any_edit_changes_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(SCHEMA.read_text() + "\n# a comment\n")
            self.assertNotEqual(schema_mod.load(path).hash, schema_mod.load(SCHEMA).hash)


@unittest.skipUnless(HAVE_DEPS, "run `uv sync` for the pipeline's dependencies")
class Parsing(unittest.TestCase):
    def setUp(self):
        self.schema = schema_mod.load(SCHEMA)

    def test_output_model_rejects_unknown_topics_and_bad_confidence(self):
        model = models.output_model(self.schema)
        model.model_validate({"variables": [{"id": 0, "topics": [{"topic": "smoking", "confidence": 1}]}]})
        for bad in ({"topic": "not_a_topic", "confidence": 0.5},
                    {"topic": "smoking", "confidence": 1.5}):
            with self.assertRaises(ValidationError):
                model.model_validate({"variables": [{"id": 0, "topics": [bad]}]})

    def test_the_json_schema_given_to_ollama_enumerates_the_topics(self):
        js = json.dumps(models.output_model(self.schema).model_json_schema())
        self.assertIn('"smoking"', js)

    def test_multiple_tags_with_confidences(self):
        llm = StubLLM(answer((0, [("smoking", 0.9), ("pregnancy_history", 0.85)]),
                             (1, [("income", 0.8)])))
        result = Tagger(self.schema, llm, "Demo").tag([var("a"), var("b")])
        self.assertEqual(result.tags[0], {"smoking": 0.9, "pregnancy_history": 0.85})
        self.assertEqual(result.missing, [])

    def test_repeated_topic_keeps_the_highest_confidence(self):
        llm = StubLLM(answer((0, [("smoking", 0.4), ("smoking", 0.8)])))
        self.assertEqual(Tagger(self.schema, llm, "D").tag([var("a")]).tags[0], {"smoking": 0.8})

    def test_unanswered_variables_are_reported(self):
        llm = StubLLM(answer((0, [("income", 0.8)])))
        self.assertEqual(Tagger(self.schema, llm, "D").tag([var("a"), var("b")]).missing, [1])

    def test_prompt_carries_topics_variables_and_format(self):
        system, user = Tagger(self.schema, StubLLM(), "Demo").messages([var("W8SMOKE", "Smokes now")])
        self.assertIn("smoking: Smoking.", system.content)
        self.assertIn('"properties"', system.content)            # the parser's format instructions
        self.assertIn('"name": "W8SMOKE"', user.content)


@unittest.skipUnless(HAVE_DEPS, "run `uv sync` for the pipeline's dependencies")
class Retrying(unittest.TestCase):
    def setUp(self):
        self.schema = schema_mod.load(SCHEMA)

    def test_bad_reply_is_retried(self):
        llm = StubLLM("not json", answer((0, [("sleep", 0.9)])))
        done, failed, used = cli.tag_batch(Tagger(self.schema, llm, "D"), [var("a")], retries=2)
        self.assertEqual((done, failed, used), ({0: {"sleep": 0.9}}, [], 1))

    def test_skipped_variables_are_asked_again(self):
        llm = StubLLM(answer((0, [("sleep", 0.9)])), answer((0, [("income", 0.7)])))
        done, failed, _ = cli.tag_batch(Tagger(self.schema, llm, "D"), [var("a"), var("b")], retries=1)
        self.assertEqual(done, {0: {"sleep": 0.9}, 1: {"income": 0.7}})
        self.assertEqual(failed, [])

    def test_gives_up_and_reports(self):
        llm = StubLLM(*[ConnectionError("down")] * 10)
        done, failed, _ = cli.tag_batch(Tagger(self.schema, llm, "D"), [var("a"), var("b")], retries=1)
        self.assertEqual((done, failed), ({}, [0, 1]))


@unittest.skipUnless(HAVE_DEPS, "run `uv sync` for the pipeline's dependencies")
class Store(unittest.TestCase):
    def test_resume_skips_current_and_redoes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = TagStore(Path(tmp))
            s.add([{"file": "f", "variable": "a", "topics": {"sleep": 0.9}, "schema": "new"},
                   {"file": "f", "variable": "b", "topics": {"sleep": 0.9}, "schema": "old"}])
            s = TagStore(Path(tmp))                     # as a second run would
            self.assertTrue(s.is_current("f/a", "new"))
            self.assertFalse(s.is_current("f/b", "new"))
            self.assertFalse(s.is_current("f/c", "new"))

    def test_torn_last_line_is_ignored_and_compact_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = TagStore(Path(tmp))
            s.add([{"file": "f", "variable": "b", "topics": {}, "schema": "x"},
                   {"file": "f", "variable": "a", "topics": {}, "schema": "x"},
                   {"file": "f", "variable": "a", "topics": {"sleep": 1}, "schema": "x"}])
            with s.path.open("a") as fh:
                fh.write('{"file": "f", "varia')          # interrupted mid-write
            s = TagStore(Path(tmp))
            s.compact(["f/a", "f/b"])
            lines = [json.loads(x) for x in s.path.read_text().splitlines()]
            self.assertEqual([x["variable"] for x in lines], ["a", "b"])
            self.assertEqual(lines[0]["topics"], {"sleep": 1})


@unittest.skipUnless(HAVE_DEPS, "run `uv sync` for the pipeline's dependencies")
class EndToEnd(unittest.TestCase):
    """A whole run against a tiny dataset: identifier by rule, the rest by the
    stub, then the site build picks the tags up."""

    def test_run_then_build(self):
        import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ds = root / "demo"
            (ds / "dictionaries" / "1y").mkdir(parents=True)
            (ds / "dataset.toml").write_text(
                '[dataset]\nkey = "demo"\nname = "Demo"\nidentifier = "id"\n'
                '[wave]\nlist = [{ key = "1y" }]\n')
            (ds / "files.csv").write_text("file,wave,description\nmain,1y,Main\n")
            (ds / "dictionaries" / "1y" / "main.csv").write_text(
                "pos,variable,variable_label\n1,id,Identifier\n2,smk,Smokes\n3,inc,Income\n")

            stub = StubLLM(answer((0, [("smoking", 0.9)]), (1, [("income", 0.8), ("benefits", 0.2)])))
            old = corpus.DATASETS
            corpus.DATASETS = root
            original = cli.ollama
            cli.ollama = lambda *a, **k: stub
            try:
                code = cli.main(["demo", "--batch-size", "5", "--workers", "1"])
            finally:
                corpus.DATASETS = old
                cli.ollama = original
            self.assertEqual(code, 0)
            tags = {json.loads(x)["variable"]: json.loads(x)
                    for x in (ds / "tags" / "tags.jsonl").read_text().splitlines()}
            self.assertEqual(tags["id"]["topics"], {"identifiers": 1.0})
            self.assertEqual(tags["smk"]["topics"], {"smoking": 0.9})
            self.assertTrue((ds / "tags" / "schema.json").exists())

            p = build.Problems()
            loaded = build.load_dataset(ds, p)
            self.assertEqual(p.errors, [])
            by_key = loaded["tags"]["by_key"]
            self.assertEqual(by_key[("main", "inc")], [["income", 0.8]])   # 0.2 is below the floor
            self.assertEqual(len(stub.calls), 1)                            # identifier needed no model


if __name__ == "__main__":
    unittest.main()
