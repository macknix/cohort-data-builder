# Next Steps raw data dictionaries (not committed)

This folder holds the UK Data Service's RTF data dictionaries for Next Steps.
Git ignores everything here except this note: the RTFs stay on your machine,
and what is committed is the dictionaries parsed from them, in
`../dictionaries/`.

```
raw/
  5545/
    <file>_ukda_data_dictionary.rtf
```

For example `raw/5545/ns9_2022_main_interview_ukda_data_dictionary.rtf`.

**Where they come from.** Next Steps is one UKDS study, SN 5545 (these were
taken from the 18th edition, February 2025). Its download ships the
dictionaries in `mrdoc/ukda_data_dictionaries/`, in three subfolders
(`safeguarded_eul/`, `household_grids/`, `activity_histories/`), or zipped as
`mrdoc/ukda_data_dictionaries.zip`. Copy all 52 RTFs, from every subfolder,
into `raw/5545/` with no subfolders.

**Then parse them** from the repository root:

```
python3 tools/parse_dictionaries.py next_steps
```

This writes `datasets/next_steps/dictionaries/<wave>/<file>.csv` for every
file in `files.csv`, and fails if an RTF is missing or its variable count does
not match the count the RTF declares. Commit the result.
