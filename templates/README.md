# {{dataset}}: {{count}}

Variables from {{full_name}}, selected with survey-merge on {{created}}.
{{languages}}

**This archive contains no study data.** You supply the data files; the
scripts read them and write the merged result to `output/`.

## 1. Get the data files

Download the data from the UK Data Service ({{ukds_url}}) and put the files
below in the `data/` folder. Everything goes in that one folder; subfolders
are fine, so a UKDS download can be unzipped into it as it is. Any format
works — `.tab`, `.dta` (Stata), `.sav` (SPSS) or `.csv` — the scripts choose
how to read each file from its extension.

{{files}}

Keep the data somewhere else already? Set `DATA_DIR` at the top of the merge
script instead of copying it.

## 2. Run it

{{run}}

## What you get

- `output/merged.{{ext}}`: one row per person, joined on `{{identifier}}`, one
  column per selected variable. People missing from a file get empty cells
  for that file's variables.{{format_note}}
- `output/<file>_long.{{ext}}`: for any file with more than one row per person
  (household grids, activity and relationship histories). These cannot be
  joined one-to-one, so they are written on their own, with `{{identifier}}`
  to link them.
- `codebook.csv`: each output column's source file, variable, label, value
  labels, missing-value codes and topics (where the variable has been tagged;
  topics are assigned by a language model, with its confidence).

{{missing_note}}

Values are otherwise exactly as deposited: nothing is recoded. Check each
variable's value labels in `codebook.csv` before analysing it.

## What is in here

{{contents}}
    codebook.csv       what every output column is
    data/              where the data files go
    output/            created on the first run
    R/load_data.R      finds and reads data files; the read call follows the extension
    R/merge.R          your selection and the merge — run this
    python/load_data.py
    python/merge.py    the same in Python — run this
    python/requirements.txt
