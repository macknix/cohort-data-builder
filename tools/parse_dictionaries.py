#!/usr/bin/env python3
"""Build every dataset's dictionaries from its raw UKDA RTF files.

    python3 tools/parse_dictionaries.py              # every dataset with a raw/ folder
    python3 tools/parse_dictionaries.py next_steps   # just one

For each dataset it reads

    datasets/<key>/raw/<study>/<file>_ukda_data_dictionary.rtf   the source, committed
    datasets/<key>/files.csv                                     which files, which wave

and writes

    datasets/<key>/dictionaries/<wave>/<file>.csv                generated, not committed

The dictionaries folder is rebuilt from scratch each time, so it never holds a
file the raw folder no longer explains. Where one file is deposited under two
studies, files.csv's `study` column says which copy to use. Standard library
only. Run it before build.py, and after changing anything under raw/ or a
wave in files.csv.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ukda_rtf_to_csv import SUFFIX, parse, rtf_to_text, write_csv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"


def parse_dataset(folder: Path) -> tuple[int, list[str]]:
    """Returns (dictionaries written, problems)."""
    problems: list[str] = []
    raw = folder / "raw"
    with (folder / "files.csv").open(newline="", encoding="utf-8-sig") as fh:
        files = list(csv.DictReader(fh))

    sources: dict[str, list[Path]] = {}
    for p in sorted(raw.rglob(f"*{SUFFIX}")):
        sources.setdefault(p.name[: -len(SUFFIX)], []).append(p)
    listed = {r["file"].strip() for r in files}
    for stem in sorted(set(sources) - listed):
        print(f"  note: raw/{sources[stem][0].relative_to(raw)} has no row in files.csv; skipped")

    out = folder / "dictionaries"
    if out.exists():
        shutil.rmtree(out)

    written = 0
    for r in files:
        name, wave, study = r["file"].strip(), r["wave"].strip(), (r.get("study") or "").strip()
        found = sources.get(name, [])
        if len(found) > 1:
            found = [p for p in found if p.parent.name == study] or found[:1]
        if not found:
            problems.append(f"{name}: no {name}{SUFFIX} under raw/")
            continue
        rows, declared = parse(rtf_to_text(found[0].read_bytes()))
        if not rows:
            problems.append(f"{name}: no variables found in {found[0].relative_to(raw)}")
            continue
        # The RTF's own count is the check that nothing was silently skipped.
        if declared is not None and declared != len(rows):
            problems.append(f"{name}: the RTF declares {declared} variables but {len(rows)} were parsed")
            continue
        write_csv(rows, out / wave / f"{name}.csv")
        written += 1
    return written, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("datasets", nargs="*", help="dataset keys; default: every one with a raw/ folder")
    args = ap.parse_args(argv)

    keys = args.datasets or sorted(p.name for p in DATASETS.iterdir() if (p / "raw").is_dir())
    if not keys:
        print("No dataset has a raw/ folder.", file=sys.stderr)
        return 1
    failed = 0
    for key in keys:
        folder = DATASETS / key
        if not (folder / "raw").is_dir():
            print(f"{key}: no raw/ folder", file=sys.stderr)
            failed += 1
            continue
        written, problems = parse_dataset(folder)
        for p in problems:
            print(f"  error: {p}", file=sys.stderr)
        failed += bool(problems)
        print(f"{key}: {written} dictionaries written to datasets/{key}/dictionaries/"
              + (f", {len(problems)} failed" if problems else ""))
    if not failed:
        print("Next: python3 build.py")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
