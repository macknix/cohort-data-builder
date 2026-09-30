# Adding a dataset: the metadata template

Each dataset is one folder under `datasets/`. It holds **metadata only**: what
each file and variable is. No study data goes in this repository, and nothing
here reads a data file.

```
datasets/
  <key>/
    dataset.toml               about the study
    files.csv                  one row per data file
    raw/
      <study>/                 one folder per UKDS study number
        <file>_ukda_data_dictionary.rtf   the deposit's own data dictionaries
    tags/                      optional: topic tags, written by `python -m enrich`
    dictionaries/              GENERATED from raw/, not committed
      <wave>/                  one folder per wave, named by its key (age)
        <file>.csv             one per data file: its variables
```

You commit `dataset.toml`, `files.csv`, `raw/` and `tags/`. The dictionaries
are built from `raw/`:

```
python3 tools/parse_dictionaries.py            # every dataset
python3 tools/parse_dictionaries.py <key>      # one
python3 build.py                               # then the site
```

For example `raw/9347/bcs11_age51_main_ukda_data_dictionary.rtf` becomes
`dictionaries/51y/bcs11_age51_main.csv`. Re-run it after changing anything
under `raw/` or a wave in `files.csv`; it rebuilds the folder from scratch.

`python3 build.py --check` validates a dataset against everything below, and
CI runs the parse and the same check on every pull request.

## `dataset.toml`

| Field | Required | Example | Notes |
|---|---|---|---|
| `[dataset] key` | yes | `next_steps` | Must equal the folder name. Lower case, digits, `_`. Used in URLs (`#next_steps`). |
| `[dataset] name` | yes | `Next Steps` | Short name, shown in the picker. |
| `[dataset] full_name` | no | `Next Steps (Longitudinal Study of Young People in England)` | Shown under the site name. |
| `[dataset] description` | no | One or two sentences | Shown before anything is searched. |
| `[dataset] identifier` | yes | `NSID` | The column that identifies a person in every file. Matched ignoring case. The download merges on it. |
| `[dataset] ukds_url` | no | UKDS series page | Where to get the data; linked from the site and the download's README. |
| `[wave] term` / `plural` | no | `sweep` / `sweeps` | What one round of collection is called. |
| `[wave] list` | yes | `{ key = "14y", label = "Sweep 1, 2004" }` | Every wave, **in time order**. `key` is short (it labels the axis); `label` is shown on hover and in details. Files that span waves go in a final cross-wave entry such as `xwave`. |

## `files.csv`

One row per data file. UTF-8, comma-separated, with a header row.

| Column | Required | Example | Notes |
|---|---|---|---|
| `file` | yes | `wave_one_lsype_young_person_2020` | The data file's name **without extension or folder**, exactly as UKDS names it. Must be unique within the dataset: all files for a download live in one data folder, and the scripts find each one by this name whatever its format (`.tab`, `.dta`, `.sav`, `.csv`). |
| `wave` | yes | `14y` | A `key` from `[wave] list`. The file's dictionary must be in the folder of the same name. |
| `description` | yes (may be empty) | `Sweep 1 (Age 14) Young Person Data File` | From the deposit's file information table. |
| `study` | no | `5545` | UKDS study number: the `raw/` folder the file's RTF is in. Needed only when one file is deposited under two studies, to say which copy to use. |

If the same file is deposited under two waves (BCS70's
`bcs70_age16_school_type` is in both the 16y and 42y deposits), list it once,
under the wave it describes.

## `dictionaries/<wave>/<file>.csv` (generated)

Written by `tools/parse_dictionaries.py`, one per row of `files.csv`, in the
folder for that file's wave (`dictionaries/25y/`, `dictionaries/xwave/`, …).
One row per variable, in file order. You do not edit these; the columns are
listed so it is clear what the site and the tagging read.

| Column | Required | Example | Notes |
|---|---|---|---|
| `pos` | yes | `3` | Position in the file. |
| `variable` | yes | `W8DCHSEX` | Name as in the data file. Unique within the file (ignoring case). |
| `variable_label` | yes | `Sex of others who live here` | `NA` or empty if none. |
| `variable_type` | no | `numeric` | |
| `measurement_level` | no | `NOMINAL` | `NOMINAL`, `ORDINAL` or `SCALE`; others are allowed and appended to the filter. |
| `spss_user_missing_values` | no | `-9.0 thru -8.0 and -1.0` | As UKDA writes it; see below. `NA` if none. |
| `value_labels_json` | no | `[{"value": "-9.0", "label": "Refused"}, ...]` | JSON list of `{value, label}`. `[]` or `NA` if none. |

The identifier column should appear in every file's dictionary. A file
without it is still searchable, but the site will not let its variables into
a download, because there is nothing to merge them on.

### How missing-value codes are read

The download's **missing codes to NA** option replaces, per variable:

1. the codes declared in `spss_user_missing_values`, and
2. any **negative** code that has a value label (many variables declare
   nothing but label `-2` "Not known").

UKDA writes a list of discrete missing codes in the same `A thru B and C`
form as a genuine range, so the build reads it conservatively:

| Declared | Read as |
|---|---|
| `-9.0 thru -1.0` (both ends negative) | the range -9 to -1 |
| `-1.0 thru 8.0` (reaches a non-negative value) | the two codes -1 and 8, **not** the range: in BCS70 `bd3inc` the income bands 0–6 lie between them |
| `-1.79…e+308 thru -1.0` | -1 and below |
| `97.0 thru 1.79…e+308 and 0.0` | 97 and above, and 0 |
| `-8.0 thru None` | the single code -8 |

Every download's `codebook.csv` lists exactly which codes each column uses.

## Getting the raw dictionaries

Copy the deposit's RTF data dictionaries into `raw/<study>/`. A UKDS download
ships them in `mrdoc/ukda_data_dictionary/` or `mrdoc/ukda_data_dictionaries/`
(sometimes zipped as `ukda_data_dictionaries.zip`: unzip it first). Each file is
`<file>_ukda_data_dictionary.rtf`, where `<file>` is the data file's name, and
that name is what goes in `files.csv`.

Then write `files.csv` (the deposit's file information table has the
descriptions; the wave for each file is yours to decide) and `dataset.toml`,
and run the parse and `python3 build.py --check`.

The parse checks each dictionary's variable count against the count the RTF
itself declares, and stops on any difference. An RTF in `raw/` with no row in
`files.csv` is skipped with a note.

Where the raw files came from:

- `bcs70`: the UKDS tab deposits in `bcs70-core-data/bcs70/UKDS/*/mrdoc/`,
  22 studies. `bcs70_age16_school_type` is deposited under both 3535 (16y)
  and 7473 (42y); the two copies are identical and `files.csv` uses 3535.
- `next_steps`: SN 5545, 18th edition, `mrdoc/ukda_data_dictionaries/`.

`tools/ukda_rtf_to_csv.py` is the converter underneath; it can also be run on
its own against a folder, a zip or a single `.rtf` to inspect one deposit.

## Checklist

- [ ] `datasets/<key>/dataset.toml` with `key`, `name`, `identifier` and every wave in order
- [ ] `files.csv`: one row per data file, unique `file`, valid `wave`
- [ ] an RTF under `raw/<study>/` for every file in `files.csv`
- [ ] `python3 tools/parse_dictionaries.py <key>` runs without errors
- [ ] `python3 build.py --check` passes with no errors
- [ ] `python3 build.py && python3 -m http.server -d site` and search a few known variables
