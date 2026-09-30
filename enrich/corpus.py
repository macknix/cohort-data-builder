"""Reading a dataset's variables from datasets/<key>/, for tagging.

Reads the same metadata build.py does - dataset.toml, files.csv and the
dictionaries - and nothing else. No data file is opened.
"""

from __future__ import annotations

import csv
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
MAX_VALUES = 14          # value labels shown to the model per variable
MAX_VALUE_CHARS = 300

csv.field_size_limit(1 << 30)


@dataclass
class Variable:
    file: str
    name: str
    label: str
    wave: str
    wave_label: str
    file_description: str
    level: str
    values: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Names are only unique within a file."""
        return f"{self.file}/{self.name}"

    def for_prompt(self, i: int) -> dict:
        """What the model sees. Value labels are what often makes a terse
        label legible, so the first few go in, trimmed."""
        values = "; ".join(f"{v.get('value', '').removesuffix('.0')}={v.get('label', '')}"
                           for v in self.values[:MAX_VALUES])
        if len(values) > MAX_VALUE_CHARS:
            values = values[:MAX_VALUE_CHARS] + "…"
        out = {"id": i, "name": self.name, "label": self.label or "(no label)",
               "file": self.file_description or self.file,
               "wave": self.wave_label or self.wave}
        if values:
            out["values"] = values
        return out


@dataclass
class Dataset:
    key: str
    name: str
    identifier: str
    variables: list[Variable]


def datasets() -> list[str]:
    return sorted(p.name for p in DATASETS.iterdir() if (p / "dataset.toml").exists())


def load(key: str) -> Dataset:
    folder = DATASETS / key
    if not (folder / "dataset.toml").exists():
        raise SystemExit(f"No dataset called {key!r}. Choose from: {', '.join(datasets())}")
    cfg = tomllib.loads((folder / "dataset.toml").read_text("utf-8"))
    labels = {w["key"]: w.get("label", "") for w in cfg["wave"]["list"]}
    order = {w["key"]: i for i, w in enumerate(cfg["wave"]["list"])}

    with (folder / "files.csv").open(newline="", encoding="utf-8-sig") as fh:
        files = sorted(csv.DictReader(fh), key=lambda r: (order.get(r["wave"], 999), r["file"]))

    variables = []
    for f in files:
        path = folder / "dictionaries" / f["wave"] / f"{f['file']}.csv"
        if not path.exists():
            raise SystemExit(f"No dictionary for {f['file']}. Build them first: "
                             f"python3 tools/parse_dictionaries.py {key}")
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get("value_labels_json") or "").strip()
                try:
                    values = json.loads(raw) if raw and raw != "NA" else []
                except json.JSONDecodeError:
                    values = []
                clean = lambda s: "" if (s or "").strip() in ("", "NA") else s.strip()  # noqa: E731
                variables.append(Variable(
                    file=f["file"], name=row["variable"].strip(),
                    label=clean(row.get("variable_label")),
                    wave=f["wave"], wave_label=labels.get(f["wave"], ""),
                    file_description=(f.get("description") or "").strip(),
                    level=clean(row.get("measurement_level")),
                    values=values or [],
                ))
    return Dataset(key=key, name=cfg["dataset"]["name"],
                   identifier=cfg["dataset"]["identifier"], variables=variables)
