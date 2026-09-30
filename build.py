#!/usr/bin/env python3
"""Validate every dataset under datasets/ and build the site's data.

    python3 build.py            # validate and write site/data/
    python3 build.py --check    # validate only

Standard library only. Reads metadata (dataset.toml, files.csv, the dictionary
CSVs) and the code templates; never a data file. The layout it expects is
defined in docs/metadata-spec.md, and every rule there is enforced here.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
TEMPLATES = ROOT / "templates"
OUT = ROOT / "site" / "data"

FILE_COLUMNS = ["file", "wave", "description"]
DICT_COLUMNS = ["pos", "variable", "variable_label", "variable_type",
                "measurement_level", "spss_user_missing_values", "value_labels_json"]
LEVELS = ["NOMINAL", "ORDINAL", "SCALE"]
KEY_OK = re.compile(r"^[a-z][a-z0-9_]*$")
FILE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")

# The templates the download is assembled from, and the placeholders each must
# still contain. site/js/codegen.js substitutes these; a template edited so
# one stopped matching would ship a literal {{...}} into someone's script.
TEMPLATE_FILES = {
    "r/load_data.R": (),
    "r/merge.R": ("dataset", "created", "identifier", "missing_to_na", "selection",
                  "missing_codes", "output_format", "labels", "value_labels"),
    "python/load_data.py": (),
    "python/merge.py": ("dataset", "created", "identifier", "missing_to_na", "selection",
                        "missing_codes", "output_format", "labels", "value_labels"),
    "python/requirements.txt": (),
    "README.md": ("dataset", "full_name", "created", "count", "files", "languages", "contents",
                  "ext", "format_note",
                  "identifier", "ukds_url", "missing_note", "run"),
    "data-README.md": ("dataset", "files", "ukds_url"),
    "project.Rproj": (),
}


class Problems:
    """Errors stop the build; warnings are printed and the build continues."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def clean(value: str | None) -> str | None:
    """The dictionaries spell 'no value' as an empty cell or a literal NA."""
    if value is None:
        return None
    value = value.strip()
    return None if value in ("", "NA") else value


def number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_missing(text: str | None) -> tuple[list[float], list[list[float | None]], bool]:
    """SPSS user-missing declarations, as written by the UKDA dictionary tool.

        A thru B [and C]    see below
        A thru None         one discrete value
        -1.79...e+308 thru B   LOWEST thru B: a range, open end None
        A thru 1.79...e+308    A thru HIGHEST: likewise

    The tool writes a list of discrete missing values in the same "A thru B and
    C" form as a real range, so the form alone does not say which it is.
    BCS70's bd3inc shows the cost of guessing wrong: "-1.0 thru 8.0" labels -1
    "no info" and 8 "refused", with the income bands 0-6 between them. So:

      - an open-ended range is a range;
      - A thru B with both ends negative is the range between them, which
        removes nothing the negative-code rule in na_codes() would not;
      - otherwise A and B are two discrete values.

    Returns (values, ranges, understood). A range is [lo, hi] with lo <= hi and
    None for an open end.
    """
    if not text:
        return [], [], True
    m = re.fullmatch(r"\s*(\S+)?\s*thru\s+(\S+)(?:\s+and\s+(\S+))?\s*", text)
    if not m:
        return [], [], False
    a, b, extra = m.groups()
    values: list[float] = []
    ranges: list[list[float | None]] = []

    def bound(s: str | None) -> float | None:
        if s is None or s == "None":
            return None
        x = number(s)
        return None if x is None or abs(x) > 1e300 else x

    lo, hi = bound(a), bound(b)
    if a is not None and a != "None" and number(a) is None:
        return [], [], False
    if b != "None" and number(b) is None:
        return [], [], False
    if b == "None":
        if lo is not None:
            values.append(lo)
    elif lo is None or hi is None:
        ranges.append([lo, hi])
    elif lo == hi:
        values.append(lo)
    elif lo < 0 and hi < 0:
        ranges.append([min(lo, hi), max(lo, hi)])
    else:
        values.extend([lo, hi])
    if extra is not None:
        x = number(extra)
        if x is None:
            return [], [], False
        values.append(x)
    return values, ranges, True


def na_codes(missing_text: str | None, labels: list[dict]) -> dict | None:
    """What 'missing codes to NA' replaces for one variable.

    The declared SPSS user-missing values, plus any negative code that carries
    a value label. The second matters: many BCS70 variables declare nothing,
    yet label -2 "Not known" or -1 "Not applicable".
    """
    values, ranges, _ = parse_missing(missing_text)
    covered = set(values)
    for v in labels:
        x = number(str(v.get("value", "")))
        if x is None or x >= 0 or x in covered:
            continue
        if any((lo is None or x >= lo) and (hi is None or x <= hi) for lo, hi in ranges):
            continue
        values.append(x)
        covered.add(x)
    if not values and not ranges:
        return None
    tidy = lambda x: int(x) if x is not None and float(x).is_integer() else x  # noqa: E731
    return {"values": sorted(tidy(v) for v in values),
            "ranges": [[tidy(lo), tidy(hi)] for lo, hi in ranges]}


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def load_dataset(folder: Path, p: Problems) -> dict | None:
    where = f"datasets/{folder.name}"
    cfg_path = folder / "dataset.toml"
    if not cfg_path.exists():
        p.error(where, "no dataset.toml")
        return None
    try:
        cfg = tomllib.loads(cfg_path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as err:
        p.error(f"{where}/dataset.toml", f"not valid TOML: {err}")
        return None

    ds = cfg.get("dataset", {})
    for key in ("key", "name", "identifier"):
        if not ds.get(key):
            p.error(f"{where}/dataset.toml", f"[dataset] {key} is required")
    if ds.get("key") and ds["key"] != folder.name:
        p.error(f"{where}/dataset.toml", f'key "{ds["key"]}" must match the folder name')
    if ds.get("key") and not KEY_OK.match(ds["key"]):
        p.error(f"{where}/dataset.toml", "key must be lower-case letters, digits and _")

    wave_cfg = cfg.get("wave", {})
    waves = wave_cfg.get("list") or []
    wave_keys = [w.get("key") for w in waves]
    if not waves or not all(wave_keys):
        p.error(f"{where}/dataset.toml", "[wave] list must give every wave a key")
    if len(set(wave_keys)) != len(wave_keys):
        p.error(f"{where}/dataset.toml", "[wave] list has a duplicate key")

    # files.csv ---------------------------------------------------------
    files_path = folder / "files.csv"
    if not files_path.exists():
        p.error(where, "no files.csv")
        return None
    cols, file_rows = read_csv(files_path)
    missing_cols = [c for c in FILE_COLUMNS if c not in cols]
    if missing_cols:
        p.error(f"{where}/files.csv", f"missing column(s): {', '.join(missing_cols)}")
        return None

    files: list[dict] = []
    seen: set[str] = set()
    for i, r in enumerate(file_rows, start=2):
        name = (r.get("file") or "").strip()
        wave = (r.get("wave") or "").strip()
        at = f"{where}/files.csv line {i}"
        if not FILE_OK.match(name):
            p.error(at, f'file "{name}" must be a bare file name with no extension or path')
            continue
        if name.lower() in seen:
            p.error(at, f'file "{name}" is listed twice; every file name must be unique '
                        "because all files share one data folder")
            continue
        seen.add(name.lower())
        if wave not in wave_keys:
            p.error(at, f'wave "{wave}" is not in [wave] list')
            continue
        files.append({"name": name, "wave": wave,
                      "study": clean(r.get("study")),
                      "description": clean(r.get("description"))})

    # dictionaries ------------------------------------------------------
    # One folder per wave: dictionaries/<wave>/<file>.csv, where <wave> is the
    # file's wave in files.csv. The folder and the column must agree.
    dict_dir = folder / "dictionaries"
    on_disk: dict[str, Path] = {}
    for q in sorted(dict_dir.rglob("*.csv")) if dict_dir.exists() else []:
        rel = q.relative_to(folder).as_posix()
        if len(q.relative_to(dict_dir).parts) != 2:
            p.error(f"{where}/{rel}", "must be in a wave folder: dictionaries/<wave>/<file>.csv")
        elif q.stem in on_disk:
            p.error(f"{where}/{rel}", f"duplicates {on_disk[q.stem].relative_to(folder)}")
        else:
            on_disk[q.stem] = q
    for stem in sorted(set(on_disk) - {f["name"] for f in files}):
        p.error(f"{where}/{on_disk[stem].relative_to(folder)}", "has no row in files.csv")

    identifier = (ds.get("identifier") or "").lower()
    dicts: dict[str, list[dict]] = {}
    for f in files:
        path = on_disk.get(f["name"])
        at = f"{where}/dictionaries/{f['wave']}/{f['name']}.csv"
        if path is None:
            hint = (f"run `python3 tools/parse_dictionaries.py {folder.name}` to build it from raw/"
                    if (folder / "raw").is_dir() else "every file in files.csv needs a dictionary")
            p.error(at, f"missing — {hint}")
            continue
        if path.parent.name != f["wave"]:
            p.error(f"{where}/{path.relative_to(folder)}",
                    f'is in "{path.parent.name}/" but files.csv says wave "{f["wave"]}" '
                    f"(re-run tools/parse_dictionaries.py)")
            continue
        cols, rows = read_csv(path)
        absent = [c for c in DICT_COLUMNS[:3] if c not in cols]
        if absent:
            p.error(at, f"missing required column(s): {', '.join(absent)}")
            continue
        names_seen: set[str] = set()
        variables = []
        for j, r in enumerate(rows, start=2):
            name = (r.get("variable") or "").strip()
            if not name:
                p.error(f"{at} line {j}", "empty variable name")
                continue
            if name.lower() in names_seen:
                p.error(f"{at} line {j}", f'variable "{name}" appears twice')
                continue
            names_seen.add(name.lower())
            raw_labels = clean(r.get("value_labels_json"))
            try:
                labels = json.loads(raw_labels) if raw_labels else []
            except json.JSONDecodeError:
                p.warn(f"{at} line {j}", f"{name}: value_labels_json is not JSON; ignored")
                labels = []
            missing = clean(r.get("spss_user_missing_values"))
            if not parse_missing(missing)[2]:
                p.warn(f"{at} line {j}",
                       f'{name}: missing values "{missing}" not understood; not converted to NA')
            level = clean(r.get("measurement_level"))
            variables.append({
                "variable": name,
                "label": clean(r.get("variable_label")),
                "pos": clean(r.get("pos")),
                "type": clean(r.get("variable_type")),
                "measurement": level.upper() if level else None,
                "missing": missing,
                "na": na_codes(missing, labels),
                "values": labels or None,
            })
        f["hasId"] = identifier in names_seen
        if not f["hasId"]:
            p.warn(at, f'no "{ds.get("identifier")}" column, so its variables cannot be merged')
        dicts[f["name"]] = variables

    order = {k: i for i, k in enumerate(wave_keys)}
    files.sort(key=lambda f: (order.get(f["wave"], 999), f["name"]))
    return {"folder": folder, "config": cfg, "files": files, "dicts": dicts,
            "tags": load_tags(folder, dicts, p)}


# Topics below this confidence are not shown on the site at all. The site's
# own threshold (a control on the page) filters above it.
TAG_FLOOR = 0.3


def load_tags(folder: Path, dicts: dict[str, list[dict]], p: Problems) -> dict | None:
    """The topic tags written by `python -m enrich`, if there are any.

    datasets/<key>/tags/schema.json is the schema they were made with (plain
    JSON, so this stays standard library) and tags.jsonl the tags. Tags made
    with an older schema are still shown where their topics still exist, and
    counted so the build can say a re-run is due.
    """
    where = f"datasets/{folder.name}/tags"
    schema_path, tags_path = folder / "tags" / "schema.json", folder / "tags" / "tags.jsonl"
    if not tags_path.exists():
        return None
    if not schema_path.exists():
        p.warn(where, "tags.jsonl has no schema.json beside it; tags not shown")
        return None
    schema = json.loads(schema_path.read_text("utf-8"))
    known = {t["id"] for d in schema["domains"] for t in d["topics"]}
    variables = {(f, v["variable"]) for f, vs in dicts.items() for v in vs}

    by_key: dict[tuple[str, str], list[list]] = {}
    stale = unknown = 0
    with tags_path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                key = (r["file"], r["variable"])
                topics = r["topics"]
            except (json.JSONDecodeError, KeyError, TypeError):
                p.warn(f"{where}/tags.jsonl line {n}", "not a tag record; skipped")
                continue
            if key not in variables:
                unknown += 1
                continue
            if r.get("schema") != schema.get("hash"):
                stale += 1
            by_key[key] = sorted(([t, round(float(c), 2)] for t, c in topics.items()
                                  if t in known and float(c) >= TAG_FLOOR),
                                 key=lambda tc: -tc[1])
    if stale:
        p.warn(where, f"{stale:,} variable(s) were tagged with an older schema; "
                      f"re-run `python -m enrich {folder.name}` to update them")
    if unknown:
        p.warn(where, f"{unknown:,} tag record(s) name variables that no longer exist; ignored")
    return {"schema": schema, "by_key": by_key, "stale": stale}


def write_json(path: Path, payload: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def load_templates(p: Problems) -> dict[str, str]:
    out = {}
    for rel, required in TEMPLATE_FILES.items():
        path = TEMPLATES / rel
        if not path.exists():
            p.error(f"templates/{rel}", "missing")
            continue
        text = path.read_text("utf-8")
        absent = [k for k in required if "{{" + k + "}}" not in text]
        if absent:
            p.error(f"templates/{rel}", "lost placeholder(s) " +
                    ", ".join("{{" + k + "}}" for k in absent))
        out[rel] = text
    return out


def emit(built: list[dict], templates: dict[str, str]) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    today = date.today().isoformat()
    catalogue = []

    for d in built:
        cfg, files, dicts = d["config"], d["files"], d["dicts"]
        ds, wave = cfg["dataset"], cfg["wave"]
        key = ds["key"]
        wave_keys = [w["key"] for w in wave["list"]]
        levels = list(LEVELS)

        tags = d["tags"]
        topic_ids = ([t["id"] for dm in tags["schema"]["domains"] for t in dm["topics"]]
                     if tags else [])
        topic_at = {t: i for i, t in enumerate(topic_ids)}

        # The search index: one positional row per variable, because at tens of
        # thousands of rows repeated key names would dominate the payload.
        #   [name, label, fileIndex, waveIndex, levelIndex, topics?]
        # topics, when tagged, is flat: [topicIndex, percent, topicIndex, percent, ...]
        index = []
        tagged = 0
        for i, f in enumerate(files):
            for v in dicts.get(f["name"], []):
                lvl = v["measurement"]
                if lvl and lvl not in levels:
                    levels.append(lvl)
                row = [v["variable"], v["label"] or "", i, wave_keys.index(f["wave"]),
                       levels.index(lvl) if lvl else -1]
                found = tags["by_key"].get((f["name"], v["variable"])) if tags else None
                if found is not None:
                    tagged += 1
                    v["topics"] = found
                    row.append([x for t, c in found for x in (topic_at[t], round(c * 100))])
                index.append(row)
            write_json(OUT / key / "dict" / f"{f['name']}.json",
                       {"file": f["name"], "wave": f["wave"], "variables": dicts.get(f["name"], [])})

        index_bytes = write_json(OUT / key / "index.json", index)
        manifest = {
            "key": key,
            "name": ds["name"],
            "fullName": ds.get("full_name") or ds["name"],
            "description": " ".join((ds.get("description") or "").split()),
            "identifier": ds["identifier"],
            "ukdsUrl": ds.get("ukds_url") or "",
            "wave": {"term": wave.get("term", "wave"), "plural": wave.get("plural", "waves"),
                     "list": [{"key": w["key"], "label": w.get("label", "")} for w in wave["list"]]},
            "levels": levels,
            "files": files,
            "built": today,
            "counts": {"variables": len(index), "files": len(files)},
            "topics": {
                "name": tags["schema"].get("name", ""),
                "version": tags["schema"].get("version"),
                "domains": tags["schema"]["domains"],
                "tagged": tagged,
                "stale": tags["stale"],
            } if tags else None,
        }
        write_json(OUT / key / "manifest.json", manifest)
        catalogue.append({"key": key, "name": ds["name"], "fullName": manifest["fullName"],
                          "description": manifest["description"], **manifest["counts"]})
        print(f"{key}: {len(index):,} variables in {len(files)} files, "
              f"{tagged:,} tagged by topic (index {index_bytes / 1_048_576:.1f} MB)")

    write_json(OUT / "datasets.json", {"built": today, "datasets": catalogue})
    write_json(OUT / "templates.json", templates)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate datasets and build the site data.")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = ap.parse_args(argv)

    p = Problems()
    folders = sorted(q for q in DATASETS.iterdir() if q.is_dir()) if DATASETS.exists() else []
    if not folders:
        p.error("datasets/", "no datasets found")
    built = [d for d in (load_dataset(f, p) for f in folders) if d]
    templates = load_templates(p)

    for w in p.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if p.errors:
        for e in p.errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"{len(p.errors)} error(s); nothing written.", file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: {len(built)} dataset(s) valid.")
        return 0
    emit(built, templates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
