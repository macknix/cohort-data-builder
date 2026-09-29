"""Where tags are kept: datasets/<key>/tags/.

    tags.jsonl     one line per variable:
                   {"file", "variable", "topics": {id: confidence}, "model", "schema", "tagged"}
    schema.json    the schema the tags were made with, as the site reads it

Written one batch at a time, so an interrupted run loses at most the batches
in flight and the next run carries on from there. Compacted (sorted, one line
per variable) when a run ends, so the file diffs cleanly.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class TagStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "tags.jsonl"
        self.records: dict[str, dict] = {}
        self._lock = threading.Lock()
        if self.path.exists():
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue    # a line cut off by a crash; that variable is redone
                    self.records[f"{r['file']}/{r['variable']}"] = r

    def is_current(self, key: str, schema_hash: str) -> bool:
        r = self.records.get(key)
        return bool(r) and r.get("schema") == schema_hash

    def add(self, records: list[dict]) -> None:
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    self.records[f"{r['file']}/{r['variable']}"] = r

    def compact(self, order: list[str]) -> None:
        """Rewrite as one line per variable, in dictionary order."""
        with self._lock:
            if not self.records:
                return
            rank = {k: i for i, k in enumerate(order)}
            keys = sorted(self.records, key=lambda k: (rank.get(k, len(rank)), k))
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for k in keys:
                    fh.write(json.dumps(self.records[k], ensure_ascii=False) + "\n")
            tmp.replace(self.path)

    def write_schema(self, snapshot: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "schema.json").write_text(
            json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
