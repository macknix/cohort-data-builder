"""Reading deposited data files, for merge.py.

Nothing in here names a study: merge.py says which files and variables it
wants, and this finds and reads them. The read call is chosen from each file's
extension, so it works with whichever format you downloaded from the UK Data
Service:

    .tab .txt .dat   tab-delimited      pandas
    .csv             comma-separated    pandas
    .dta             Stata              pandas
    .sav .zsav       SPSS               pyreadstat

Files are found by name anywhere under the data folder, subfolders included,
so a UKDS download can be unzipped into it as it is. Every file is opened for
reading only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SUPPORTED_FORMATS = ("tab", "txt", "dat", "csv", "dta", "sav", "zsav")
DELIMITED = {"tab": "\t", "txt": "\t", "dat": "\t", "csv": ","}


def index_data_dir(data_dir: Path) -> dict[str, list[Path]]:
    """Every readable file under data_dir, by lower-case name without extension."""
    if not data_dir.is_dir():
        raise SystemExit(
            f"The data folder does not exist: {data_dir.resolve()}\n"
            "Put the data files there, or set DATA_DIR at the top of merge.py."
        )
    index: dict[str, list[Path]] = {}
    for path in data_dir.rglob("*"):
        if path.is_file() and path.suffix.lower().lstrip(".") in SUPPORTED_FORMATS:
            index.setdefault(path.stem.lower(), []).append(path)
    return index


def find_data_file(index: dict[str, list[Path]], file: str) -> Path | None:
    """The path to one file, or None. When the same file is present in several
    formats, the first in SUPPORTED_FORMATS is used and the choice reported."""
    hits = index.get(file.lower())
    if not hits:
        return None
    hits = sorted(hits, key=lambda p: SUPPORTED_FORMATS.index(p.suffix.lower().lstrip(".")))
    if len(hits) > 1:
        print(f"{file}: found {len(hits)} copies; using {hits[0]}")
    return hits[0]


def _pyreadstat():
    try:
        import pyreadstat
    except ImportError:
        raise SystemExit("Reading SPSS files needs pyreadstat: pip install pyreadstat") from None
    return pyreadstat


def _read_delimited(path: Path, sep: str, **kwargs) -> pd.DataFrame:
    # UKDS tab files are usually UTF-8 but not always.
    for encoding in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(path, sep=sep, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"could not decode {path}")


def read_header(path: Path) -> list[str]:
    ext = path.suffix.lower().lstrip(".")
    if ext in DELIMITED:
        return list(_read_delimited(path, DELIMITED[ext], nrows=0,
                                    quoting=3 if ext != "csv" else 0).columns)
    if ext == "dta":
        with pd.read_stata(path, iterator=True) as reader:
            return list(reader.variable_labels())
    return list(_pyreadstat().read_sav(str(path), metadataonly=True)[1].column_names)


def read_columns(path: Path, wanted: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Read only the wanted columns of one file.

    Names are matched ignoring case, because the same file can spell them
    differently in different formats, and the columns come back spelt as
    `wanted` spells them. Values are the codes as deposited: value labels are
    not applied and SPSS user-missing codes are kept, so every format gives
    the same numbers. Returns the data and the wanted names not found.
    """
    ext = path.suffix.lower().lstrip(".")
    header = read_header(path)
    lower = {h.lower(): h for h in header}
    found = [w for w in wanted if w.lower() in lower]
    columns = [lower[w.lower()] for w in found]

    if ext in DELIMITED:
        data = _read_delimited(path, DELIMITED[ext], usecols=columns, skipinitialspace=True,
                               quoting=3 if ext != "csv" else 0, low_memory=False)
    elif ext == "dta":
        data = pd.read_stata(path, columns=columns, convert_categoricals=False)
    else:
        data, _ = _pyreadstat().read_sav(str(path), usecols=columns, user_missing=True,
                                         apply_value_formats=False)

    back = {c.lower(): w for c, w in zip(columns, found)}
    data = data.rename(columns=lambda c: back[c.lower()])[found]
    return data, [w for w in wanted if w not in found]


def normalise_identifier(series: pd.Series) -> pd.Series:
    """Trimmed and upper-cased, so the same person links across files that
    formatted the identifier differently."""
    if pd.api.types.is_float_dtype(series) and (series.dropna() % 1 == 0).all():
        series = series.astype("Int64")
    return series.astype("string").str.strip().str.upper()


def apply_missing_codes(series: pd.Series, codes: dict | None) -> pd.Series:
    """Replace one variable's missing-value codes with NA. `codes` is
    {"values": [...], "ranges": [[lo, hi], ...]}; an open end is None."""
    if codes is None or not pd.api.types.is_numeric_dtype(series):
        return series
    drop = series.isin(codes["values"])
    for lo, hi in codes["ranges"]:
        lo = float("-inf") if lo is None else lo
        hi = float("inf") if hi is None else hi
        drop |= series.between(lo, hi)
    return series.mask(drop)


def write_output(data: pd.DataFrame, path: Path, fmt: str,
                 labels: dict | None = None, value_labels: dict | None = None) -> Path:
    """Write one table as csv, dta (Stata) or sav (SPSS). `path` has no extension.

    Stata and SPSS files carry each column's label and its value labels, from
    the data dictionary, so they open ready to use. CSV has nowhere to put
    them; codebook.csv lists them instead. Stata keeps variable labels to 80
    characters, so longer ones are cut there.
    """
    file = path.with_name(f"{path.name}.{fmt}")
    if fmt == "csv":
        data.to_csv(file, index=False)
        return file
    if fmt not in ("dta", "sav"):
        raise SystemExit(f'OUTPUT_FORMAT must be "csv", "dta" or "sav", not "{fmt}".')
    labels = {c: l for c, l in (labels or {}).items() if c in data.columns}
    codes = {c: v for c, v in (value_labels or {}).items()
             if c in data.columns and pd.api.types.is_numeric_dtype(data[c])}
    # Both writers want plain object strings, not pandas' string dtype.
    data = data.astype({c: object for c in data.columns if pd.api.types.is_string_dtype(data[c])})
    if fmt == "dta":
        data.to_stata(file, write_index=False, version=118,
                      variable_labels={c: l[:80] for c, l in labels.items()},
                      value_labels={c: {int(k): v for k, v in m.items()} for c, m in codes.items()})
    else:
        _pyreadstat().write_sav(data, str(file), column_labels=labels,
                                variable_value_labels=codes)
    return file
