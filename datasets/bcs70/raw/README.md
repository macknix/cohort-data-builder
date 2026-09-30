# BCS70 raw data dictionaries (not committed)

This folder holds the UK Data Service's RTF data dictionaries for BCS70, one
subfolder per UKDS study number. Git ignores everything here except this note:
the RTFs stay on your machine, and what is committed is the dictionaries
parsed from them, in `../dictionaries/`.

```
raw/
  <study number>/
    <file>_ukda_data_dictionary.rtf
```

For example `raw/9347/bcs11_age51_main_ukda_data_dictionary.rtf`.

**Where they come from.** Each UKDS tab download of a BCS70 study ships them in
`mrdoc/ukda_data_dictionary/` (older deposits: `mrdoc/ukda_data_dictionaries.zip`,
unzip it first). Copy each study's RTFs into a folder named for its study
number, the digits in `UKDA-<number>-tab`. 22 studies, 85 RTFs:

2666, 2690, 2699, 3535, 3723, 3833, 4715, 5225, 5558, 5585, 5641, 6095, 6557,
6941, 6943, 7064, 7473, 8288, 8547, 8611, 8618, 9347

`bcs70_age16_school_type` is in both 3535 and 7473; the copies are identical,
and `files.csv` uses 3535.

**Then parse them** from the repository root:

```
python3 tools/parse_dictionaries.py bcs70
```

This writes `datasets/bcs70/dictionaries/<wave>/<file>.csv` for every file in
`files.csv`, and fails if an RTF is missing or its variable count does not
match the count the RTF declares. Commit the result.
