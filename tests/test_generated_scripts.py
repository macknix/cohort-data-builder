"""End to end: generate a download as the site does, run its R and its Python
on fabricated data files, and check both give the same, correct result.

    python3 build.py && python3 -m unittest discover -s tests

Needs node. The R half needs Rscript, and the Stata/SPSS fixtures need R's
haven to write them; the SPSS read in Python needs pyreadstat. Whatever is
missing is skipped, and says so.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HAVE_NODE = shutil.which("node") is not None
HAVE_R = shutil.which("Rscript") is not None


def r_has(pkg: str) -> bool:
    if not HAVE_R:
        return False
    out = subprocess.run(["Rscript", "-e", f"cat(requireNamespace('{pkg}', quietly=TRUE))"],
                         capture_output=True, text=True)
    return out.stdout.strip() == "TRUE"


HAVE_HAVEN = r_has("haven")
HAVE_PANDAS = importlib.util.find_spec("pandas") is not None
HAVE_PYREADSTAT = importlib.util.find_spec("pyreadstat") is not None

# Three files, three formats, one of them in a subfolder and one long.
#   bcs7072a                    .tab, ids with stray case and whitespace
#   bcs3derived                 .dta, in data/sub/
#   bcs70_age16-51_activity_histories_long   .sav, several rows per person
PICKS = [
    "bcs7072a:a0002",
    "bcs7072a:a0005a:mother_age",
    "bcs3derived:bd3inc",
    "bcs3derived:bd3psoc",
    "bcs70_age16-51_activity_histories_long:wsweep05",
]

TAB = (
    "bcsid\ta0002\ta0005a\ta0014\n"
    "b10001n \t0\t25\t1\n"
    "B10002P\t1\t-2\t2\n"
    "B10003Q\t0\t31\t-2\n"
)

MAKE_BINARY = r"""
library(haven)
args <- commandArgs(trailingOnly = TRUE)
dir.create(file.path(args[1], "sub"), showWarnings = FALSE)
dta <- data.frame(BCSID = c("B10001N", "B10002P", "B10004R"),
                  bd3inc = c(3, -1, 8), bd3psoc = c(-2, 4, -1), other = 1:3)
write_dta(dta, file.path(args[1], "sub", "bcs3derived.dta"))
sav <- data.frame(
  bcsid = c("B10001N", "B10001N", "B10002P"),
  wsweep05 = labelled_spss(c(1, 2, 9), c(Yes = 1, No = 2, Missing = 9), na_values = 9)
)
write_sav(sav, file.path(args[1], "bcs70_age16-51_activity_histories_long.sav"))
"""


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(s: str) -> float | None:
    return None if s in ("", "NA") else float(s)


@unittest.skipUnless(HAVE_NODE, "node is not installed")
@unittest.skipUnless((ROOT / "site/data/templates.json").exists(), "run build.py first")
class GeneratedScripts(unittest.TestCase):
    na = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        subprocess.run(["node", str(ROOT / "tests/generate_bundle.mjs"), "bcs70",
                        str(cls.tmp), "true" if cls.na else "false", *PICKS],
                       check=True, capture_output=True, text=True)
        data = cls.tmp / "data"
        (data / "bcs7072a.tab").write_text(TAB)
        cls.binary = HAVE_HAVEN
        if cls.binary:
            subprocess.run(["Rscript", "-e", MAKE_BINARY, str(data)], check=True,
                           capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_lang(self, lang: str) -> dict[str, list[dict]]:
        out = self.tmp / "output"
        shutil.rmtree(out, ignore_errors=True)
        cmd = (["Rscript", "R/merge.R"] if lang == "r"
               else [sys.executable, "python/merge.py"])
        res = subprocess.run(cmd, cwd=self.tmp, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"{lang} failed:\n{res.stdout}\n{res.stderr}")
        return {p.name: read(p) for p in out.glob("*.csv")}

    def check(self, got: dict[str, list[dict]]) -> None:
        merged = {r["bcsid"]: r for r in got["merged.csv"]}
        # Identifiers normalised, and the outer join keeps everyone.
        self.assertEqual(sorted(merged), ["B10001N", "B10002P", "B10003Q", "B10004R"])
        self.assertEqual(list(got["merged.csv"][0])[:3], ["bcsid", "a0002", "mother_age"])
        self.assertEqual(num(merged["B10001N"]["mother_age"]), 25)
        self.assertEqual(num(merged["B10003Q"]["a0002"]), 0)
        # Only in the .dta, so absent from the .tab's columns.
        self.assertIsNone(num(merged["B10004R"]["a0002"]))
        # -2 is labelled "Not known": NA only when converting.
        self.assertEqual(num(merged["B10002P"]["mother_age"]), None if self.na else -2)
        # bd3inc: "-1 thru 8" is -1 and 8, NOT the bands between them.
        self.assertEqual(num(merged["B10001N"]["bd3inc"]), 3)
        self.assertEqual(num(merged["B10004R"]["bd3inc"]), None if self.na else 8)
        self.assertEqual(num(merged["B10002P"]["bd3psoc"]), 4)
        self.assertEqual(num(merged["B10001N"]["bd3psoc"]), None if self.na else -2)
        # The long file is kept apart, with its SPSS user-missing code intact
        # unless converting (9 is not in the dictionary, so it survives).
        long = got["bcs70_age16-51_activity_histories_long_long.csv"]
        self.assertEqual(len(long), 3)
        self.assertNotIn("wsweep05", got["merged.csv"][0])
        self.assertIn(9.0, [num(r["wsweep05"]) for r in long])

    @unittest.skipUnless(HAVE_R and HAVE_HAVEN, "Rscript with haven is needed")
    def test_r(self):
        self.check(self.run_lang("r"))

    @unittest.skipUnless(HAVE_PANDAS and HAVE_PYREADSTAT and HAVE_HAVEN,
                         "pandas, pyreadstat and R's haven (for fixtures) are needed")
    def test_python(self):
        self.check(self.run_lang("python"))

    @unittest.skipUnless(HAVE_R and HAVE_HAVEN and HAVE_PANDAS and HAVE_PYREADSTAT,
                         "both languages are needed to compare them")
    def test_languages_agree(self):
        r, py = self.run_lang("r"), self.run_lang("python")
        self.assertEqual(sorted(r), sorted(py))
        for name in r:
            key = lambda row: tuple(row.values())  # noqa: E731
            norm = lambda rows: sorted(  # noqa: E731
                ({k: ("" if v in ("", "NA") else str(float(v)) if _isnum(v) else v)
                  for k, v in row.items()} for row in rows), key=key)
            self.assertEqual(norm(r[name]), norm(py[name]), name)


class KeepingCodes(GeneratedScripts):
    na = False


def _isnum(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    unittest.main()
