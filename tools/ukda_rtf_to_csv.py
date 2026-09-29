#!/usr/bin/env python3
"""Convert UK Data Archive RTF data dictionaries into the dictionary CSV format.

    python3 tools/ukda_rtf_to_csv.py <input> <output_dir>

<input> is one `*_ukda_data_dictionary.rtf`, a directory searched recursively
for them, or the `ukda_data_dictionaries.zip` a UKDS download ships in
`mrdoc/`. One `<file>.csv` is written per dictionary, where <file> is the data
file's name with the `_ukda_data_dictionary` suffix removed.

The columns are the ones docs/metadata-spec.md defines, so the output can be
dropped into `datasets/<key>/dictionaries/` as it stands. Standard library
only. It reads documentation, never a data file.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

SUFFIX = "_ukda_data_dictionary.rtf"
COLUMNS = ["pos", "variable", "variable_label", "variable_type",
           "measurement_level", "spss_user_missing_values", "value_labels_json"]

# Destinations whose whole group is formatting, not text.
SKIP_GROUPS = {"fonttbl", "colortbl", "stylesheet", "info", "listtable",
               "listoverridetable", "rsidtbl", "generator", "xmlnstbl"}

CONTROL = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([\r\n])", re.S)


def rtf_to_text(raw: bytes) -> str:
    """Plain text of an RTF document, paragraphs as newlines.

    Enough of RTF for what UKDA's dictionary writer emits: groups, control
    words, hex escapes in the ANSI code page and \\u escapes. Not a general
    RTF reader.
    """
    out: list[str] = []
    stack: list[bool] = []       # per group: is its text skipped?
    skipping = False
    uc_skip = 0                  # characters to drop after a \\u escape
    pos = 0
    group_start = False          # the next token is the first in a new group

    def emit(s: str) -> None:
        nonlocal uc_skip
        if skipping:
            return
        if uc_skip:
            drop = min(uc_skip, len(s))
            s, uc_skip = s[drop:], uc_skip - drop
        out.append(s)

    for m in CONTROL.finditer(raw):
        if m.start() > pos:
            emit(raw[pos:m.start()].decode("cp1252", errors="replace"))
            group_start = False
        pos = m.end()
        word, arg, hexa, sym, brace, newline = m.groups()

        if newline:
            continue
        if brace == b"{":
            stack.append(skipping)
            group_start = True
            continue
        if brace == b"}":
            skipping = stack.pop() if stack else False
            group_start = False
            continue

        first, group_start = group_start, False
        if hexa:
            emit(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
        elif sym:
            if sym == b"*" and first:
                skipping = True
            elif sym in (b"\\", b"{", b"}"):
                emit(sym.decode())
            elif sym == b"~" or sym == b" ":
                emit(" ")
            elif sym == b"\t":
                emit("\t")
        elif word:
            w = word.decode()
            if first and w in SKIP_GROUPS:
                skipping = True
            elif w in ("par", "line", "row"):
                emit("\n")
            elif w in ("tab", "cell"):
                emit("\t")
            elif w == "u" and arg is not None:
                code = int(arg)
                emit(chr(code + 65536 if code < 0 else code))
                uc_skip = 1

    if pos < len(raw):
        emit(raw[pos:].decode("cp1252", errors="replace"))
    return "".join(out)


# Positions past 999 carry a thousands separator: "Pos. = 1,427".
POS = re.compile(r"^\s*Pos\. = ([\d,]+)\s+Variable = (\S+)\s+Variable label = ?(.*)$")
TYPE = re.compile(r"This variable is\s+(\w+), the SPSS measurement level is\s+(\w+)")
MISSING = re.compile(r"^\s*SPSS user missing values = (.*)$")
VALUE = re.compile(r"^\s*Value = (\S+)\s+Label = ?(.*)$")
DECLARED = re.compile(r"^\s*Number of variables =\s*([\d,]+)")


def parse(text: str) -> tuple[list[dict], int | None]:
    """The variables in one dictionary's text, in file order, and the count
    the dictionary's own header declares."""
    rows: list[dict] = []
    declared = None
    cur: dict | None = None
    for line in text.splitlines():
        if declared is None and (m := DECLARED.match(line)):
            declared = int(m[1].replace(",", ""))
        elif m := POS.match(line):
            cur = {"pos": m[1].replace(",", ""), "variable": m[2], "variable_label": m[3].strip(),
                   "variable_type": None, "measurement_level": None,
                   "spss_user_missing_values": None, "values": []}
            rows.append(cur)
        elif cur is None:
            continue
        elif m := TYPE.search(line):
            cur["variable_type"], cur["measurement_level"] = m[1], m[2]
        elif m := MISSING.match(line):
            cur["spss_user_missing_values"] = " ".join(m[1].split())
        elif m := VALUE.match(line):
            cur["values"].append({"value": m[1], "label": m[2].strip()})
    return rows, declared


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([
                r["pos"], r["variable"], r["variable_label"] or "NA",
                r["variable_type"] or "NA", r["measurement_level"] or "NA",
                r["spss_user_missing_values"] or "NA",
                json.dumps(r["values"], ensure_ascii=False),
            ])


def sources(target: Path):
    """(file name, rtf bytes) for every dictionary in a file, dir or zip."""
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as zf:
            for name in sorted(zf.namelist()):
                if name.lower().endswith(SUFFIX):
                    yield Path(name).name, zf.read(name)
    elif target.is_dir():
        for p in sorted(target.rglob(f"*{SUFFIX}")):
            yield p.name, p.read_bytes()
    else:
        yield target.name, target.read_bytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", type=Path)
    ap.add_argument("output_dir", type=Path)
    args = ap.parse_args(argv)

    count = failed = 0
    for name, raw in sources(args.input):
        stem = name[: -len(SUFFIX)] if name.lower().endswith(SUFFIX) else Path(name).stem
        rows, declared = parse(rtf_to_text(raw))
        if not rows:
            print(f"warning: no variables found in {name}", file=sys.stderr)
            continue
        # The header's own count is the check that nothing was silently skipped.
        if declared is not None and declared != len(rows):
            print(f"error: {name} declares {declared} variables but {len(rows)} "
                  f"were parsed", file=sys.stderr)
            failed += 1
            continue
        write_csv(rows, args.output_dir / f"{stem}.csv")
        print(f"{stem}: {len(rows)} variables")
        count += 1
    print(f"Wrote {count} dictionaries to {args.output_dir}")
    return 0 if count and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
