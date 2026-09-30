"""{{dataset}}: variables selected with Cohort Data Builder on {{created}}.

Run from anywhere:  python python/merge.py
README.md lists the data files it needs.
"""

from __future__ import annotations

import sys
from functools import reduce
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from load_data import (  # noqa: E402
    apply_missing_codes, find_data_file, index_data_dir, normalise_identifier, read_columns,
    write_output,
)

# ── Settings ────────────────────────────────────────────────────────────────

# The folder holding the data files. Subfolders are searched too.
DATA_DIR = HERE.parent / "data"

# Where the results are written.
OUTPUT_DIR = HERE.parent / "output"

# The file type written: "csv", "dta" (Stata) or "sav" (SPSS). Stata and SPSS
# files carry the variable and value labels below; SPSS needs pyreadstat.
OUTPUT_FORMAT = "{{output_format}}"

# True replaces each variable's missing-value codes below with NA.
# False keeps the codes exactly as deposited.
MISSING_TO_NA = {{missing_to_na}}

# The column that identifies a person in every file.
IDENTIFIER = "{{identifier}}"

# ── Your selection ──────────────────────────────────────────────────────────

# For each data file, the variables to take from it:
#   "output_column": "variable name in the file"
SELECTION = {
{{selection}}
}

# The codes MISSING_TO_NA replaces, per output column: single values, and
# ranges as [low, high] where None is an open end. Taken from the data
# dictionary: the declared missing values plus any labelled negative code.
MISSING_CODES = {
{{missing_codes}}
}

# Labels written into Stata and SPSS files, from the data dictionary: a label
# per output column, and the value labels of each column that has them.
LABELS = {
{{labels}}
}

VALUE_LABELS = {
{{value_labels}}
}

# ── Merge ───────────────────────────────────────────────────────────────────


def main() -> None:
    index = index_data_dir(Path(DATA_DIR))

    # Check every file is present before reading any of them.
    paths = {f: find_data_file(index, f) for f in SELECTION}
    absent = [f for f, p in paths.items() if p is None]
    if absent:
        raise SystemExit(
            f"These data files were not found under {Path(DATA_DIR).resolve()}:\n"
            + "\n".join(f"  {f}" for f in absent)
            + "\nSee README.md for where to get them."
        )

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    wide = []

    for file, wanted in SELECTION.items():
        print(f"Reading {paths[file].name}")
        data, missing = read_columns(paths[file], [IDENTIFIER, *wanted.values()])
        if IDENTIFIER in missing:
            raise SystemExit(f"{file} has no {IDENTIFIER} column, so it cannot be merged.")
        if missing:
            print(f"warning: {file}: not found, skipped: {', '.join(missing)}")

        keep = {out: var for out, var in wanted.items() if var in data.columns}
        data = data[[IDENTIFIER, *keep.values()]]
        data.columns = [IDENTIFIER, *keep.keys()]
        data[IDENTIFIER] = normalise_identifier(data[IDENTIFIER])
        if MISSING_TO_NA:
            for column in keep:
                data[column] = apply_missing_codes(data[column], MISSING_CODES.get(column))

        # A file with more than one row per person (a household grid, a
        # history) cannot be joined one-to-one. It is written out on its own.
        data = data.drop_duplicates()
        if data[IDENTIFIER].duplicated().any():
            out = write_output(data, Path(OUTPUT_DIR) / f"{file}_long", OUTPUT_FORMAT,
                               LABELS, VALUE_LABELS)
            print(f"{file} has several rows per {IDENTIFIER}; written separately to {out}")
            continue
        wide.append(data)

    if wide:
        merged = reduce(lambda a, b: a.merge(b, on=IDENTIFIER, how="outer"), wide)
        out = write_output(merged, Path(OUTPUT_DIR) / "merged", OUTPUT_FORMAT,
                           LABELS, VALUE_LABELS)
        print(f"Wrote {len(merged)} rows and {merged.shape[1]} columns to {out}")


if __name__ == "__main__":
    main()
