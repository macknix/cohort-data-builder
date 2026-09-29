#!/usr/bin/env python3
"""Move a dataset's dictionaries into one folder per wave.

    python3 tools/shuffle_dictionaries.py datasets/<key>

Reads each file's wave from files.csv and moves `dictionaries/**/<file>.csv`
to `dictionaries/<wave>/<file>.csv`. Safe to re-run: files already in place
are left alone. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset", type=Path, help="the dataset folder, e.g. datasets/next_steps")
    args = ap.parse_args(argv)

    root = args.dataset / "dictionaries"
    with (args.dataset / "files.csv").open(newline="", encoding="utf-8-sig") as fh:
        waves = {r["file"].strip(): r["wave"].strip() for r in csv.DictReader(fh)}

    found = {p.stem: p for p in root.rglob("*.csv")}
    moved = unlisted = 0
    for stem, path in sorted(found.items()):
        wave = waves.get(stem)
        if wave is None:
            print(f"warning: {path} has no row in files.csv; left where it is", file=sys.stderr)
            unlisted += 1
            continue
        target = root / wave / f"{stem}.csv"
        if path != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
            moved += 1

    missing = sorted(set(waves) - set(found))
    for stem in missing:
        print(f"warning: no dictionary for {stem}", file=sys.stderr)
    for d in sorted(root.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"Moved {moved} dictionaries into wave folders under {root}")
    return 1 if missing or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
