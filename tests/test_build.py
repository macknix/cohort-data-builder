"""The rules build.py and the RTF converter enforce. Standard library only."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402
import ukda_rtf_to_csv as rtf  # noqa: E402


class MissingValues(unittest.TestCase):
    def test_negative_range_is_a_range(self):
        self.assertEqual(build.parse_missing("-9.0 thru -1.0"), ([], [[-9.0, -1.0]], True))

    def test_reversed_negative_range_is_ordered(self):
        self.assertEqual(build.parse_missing("-1.0 thru -8.0 and -9.0"),
                         ([-9.0], [[-8.0, -1.0]], True))

    def test_range_reaching_real_values_is_two_codes(self):
        # BCS70 bd3inc: -1 "no info", 8 "refused", income bands 0-6 between.
        self.assertEqual(build.parse_missing("-1.0 thru 8.0"), ([-1.0, 8.0], [], True))

    def test_thru_none_is_one_code(self):
        self.assertEqual(build.parse_missing("-8.0 thru None"), ([-8.0], [], True))

    def test_open_ends(self):
        self.assertEqual(build.parse_missing("-1.7976931348623155e+308 thru -1.0"),
                         ([], [[None, -1.0]], True))
        self.assertEqual(build.parse_missing("97.0 thru 1.7976931348623157e+308 and 0.0"),
                         ([0.0], [[97.0, None]], True))

    def test_unreadable_is_reported_not_guessed(self):
        self.assertEqual(build.parse_missing("LOWEST thru -1"), ([], [], False))

    def test_na_codes_add_labelled_negatives(self):
        labels = [{"value": "-2.0", "label": "Not known"}, {"value": "1.0", "label": "Yes"}]
        self.assertEqual(build.na_codes(None, labels), {"values": [-2], "ranges": []})

    def test_na_codes_skip_values_inside_a_range(self):
        labels = [{"value": "-3.0", "label": "Refused"}]
        self.assertEqual(build.na_codes("-9.0 thru -1.0", labels),
                         {"values": [], "ranges": [[-9, -1]]})

    def test_nothing_to_convert(self):
        self.assertIsNone(build.na_codes(None, [{"value": "1.0", "label": "Yes"}]))


SAMPLE_RTF = rb"""{\rtf1\ansi\deff0{\fonttbl{\f0\fswiss MS Sans Serif;}}{\colortbl;\red0\green0\blue0;}
{\f2\fs20\cf1 File Name = \f2\fs20\cf5 demo\par }{\f2\fs20\cf1 Number of variables = \cf5 2\par }
{\cf1\b\par Pos. = }{\f2\fs20\cf4 1	}{\b\cf1 Variable = }{\f2\fs20\cf4 NSID	}{\b\cf1 Variable label = }{\cf4 Cohort member identifier \par }
{\cf1\b\par Pos. = }{\f2\fs20\cf4 1,002	}{\b\cf1 Variable = }{\f2\fs20\cf4 W8SEX	}{\b\cf1 Variable label = }{\cf4 Sex \'96 as reported \par }
{\cf3 This variable is  }{\cf5\i numeric}{\cf3, the SPSS measurement level is }{\cf5\i NOMINAL\par }
{\cf1 SPSS user missing values = \cf4 -9.0 \cf1\fs16\ thru \cf4\fs20 -8.0 \cf1\fs16\ and \cf4\fs20 -1.0\par }
{\cf3\ul\fs16 Value label information for W8SEX\par }
{\cf1\fs16	Value = }{\cf4\fs16 -9.0	}{\cf1\fs16 Label = }{\cf4\fs16 Refused\par }
{\cf1\fs16	Value = }{\cf4\fs16 1.0	}{\cf1\fs16 Label = }{\cf4\fs16 Male   \par }}
"""


class RtfConverter(unittest.TestCase):
    def test_parses_the_ukda_layout(self):
        rows, declared = rtf.parse(rtf.rtf_to_text(SAMPLE_RTF))
        self.assertEqual(declared, 2)
        self.assertEqual([r["variable"] for r in rows], ["NSID", "W8SEX"])
        sex = rows[1]
        self.assertEqual(sex["pos"], "1002")                 # thousands separator
        self.assertEqual(sex["variable_label"], "Sex – as reported")   # cp1252 \'96
        self.assertEqual(sex["measurement_level"], "NOMINAL")
        self.assertEqual(sex["spss_user_missing_values"], "-9.0 thru -8.0 and -1.0")
        self.assertEqual(sex["values"], [{"value": "-9.0", "label": "Refused"},
                                         {"value": "1.0", "label": "Male"}])

    def test_output_is_a_valid_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "demo_ukda_data_dictionary.rtf"
            src.write_bytes(SAMPLE_RTF)
            self.assertEqual(rtf.main([str(src), tmp]), 0)
            header = (Path(tmp) / "demo.csv").read_text().splitlines()[0]
            self.assertEqual(header.split(","), build.DICT_COLUMNS)

    def test_count_mismatch_fails(self):
        broken = SAMPLE_RTF.replace(rb"\cf5 2\par", rb"\cf5 3\par")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "demo_ukda_data_dictionary.rtf"
            src.write_bytes(broken)
            self.assertEqual(rtf.main([str(src), tmp]), 1)


class Datasets(unittest.TestCase):
    def test_every_committed_dataset_is_valid(self):
        if not any(build.DATASETS.glob("*/dictionaries")):
            self.skipTest("dictionaries not built: python3 tools/parse_dictionaries.py")
        p = build.Problems()
        for folder in sorted(q for q in build.DATASETS.iterdir() if q.is_dir()):
            build.load_dataset(folder, p)
        self.assertEqual(p.errors, [])

    def make(self, tmp: Path, dict_path: str) -> build.Problems:
        folder = tmp / "demo"
        (folder / Path(dict_path).parent).mkdir(parents=True)
        (folder / "dataset.toml").write_text(
            '[dataset]\nkey = "demo"\nname = "Demo"\nidentifier = "id"\n'
            '[wave]\nlist = [{ key = "1y" }, { key = "2y" }]\n')
        (folder / "files.csv").write_text("file,wave,description\nmain,1y,Main\n")
        (folder / dict_path).write_text(
            "pos,variable,variable_label\n1,id,Identifier\n2,x,Something\n")
        p = build.Problems()
        build.load_dataset(folder, p)
        return p

    def test_dictionary_in_its_wave_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.make(Path(tmp), "dictionaries/1y/main.csv").errors, [])

    def test_dictionary_in_the_wrong_wave_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = self.make(Path(tmp), "dictionaries/2y/main.csv").errors
            self.assertTrue(any('files.csv says wave "1y"' in e for e in errors), errors)

    def test_dictionary_outside_any_wave_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = self.make(Path(tmp), "dictionaries/main.csv").errors
            self.assertTrue(any("must be in a wave folder" in e for e in errors), errors)



class ParseDictionaries(unittest.TestCase):
    """tools/parse_dictionaries.py: raw RTFs in, wave folders out."""

    def make(self, tmp: Path, files_csv: str, raws: dict[str, bytes]) -> Path:
        folder = tmp / "demo"
        for rel, data in raws.items():
            (folder / "raw" / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / "raw" / rel).write_bytes(data)
        (folder / "files.csv").write_text(files_csv)
        return folder

    def test_writes_each_file_into_its_wave_folder(self):
        import parse_dictionaries
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make(Path(tmp), "file,wave,study,description\ndemo,1y,100,Demo\n",
                               {"100/demo_ukda_data_dictionary.rtf": SAMPLE_RTF})
            (folder / "dictionaries" / "old").mkdir(parents=True)
            (folder / "dictionaries" / "old" / "stale.csv").write_text("x")
            written, problems = parse_dictionaries.parse_dataset(folder)
            self.assertEqual((written, problems), (1, []))
            self.assertTrue((folder / "dictionaries" / "1y" / "demo.csv").exists())
            self.assertFalse((folder / "dictionaries" / "old").exists())   # rebuilt from scratch

    def test_a_file_in_two_studies_uses_the_one_files_csv_names(self):
        import parse_dictionaries
        other = SAMPLE_RTF.replace(b"NSID", b"OTHERID")
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make(Path(tmp), "file,wave,study,description\ndemo,1y,200,Demo\n",
                               {"100/demo_ukda_data_dictionary.rtf": other,
                                "200/demo_ukda_data_dictionary.rtf": SAMPLE_RTF})
            parse_dictionaries.parse_dataset(folder)
            text = (folder / "dictionaries" / "1y" / "demo.csv").read_text()
            self.assertIn("NSID", text)
            self.assertNotIn("OTHERID", text)

    def test_missing_rtf_is_reported(self):
        import parse_dictionaries
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make(Path(tmp), "file,wave,study,description\nabsent,1y,100,A\n",
                               {"100/demo_ukda_data_dictionary.rtf": SAMPLE_RTF})
            (folder / "dictionaries" / "1y").mkdir(parents=True)
            (folder / "dictionaries" / "1y" / "kept.csv").write_text("x")
            written, problems = parse_dictionaries.parse_dataset(folder)
            self.assertEqual(written, 0)
            self.assertTrue(problems and "absent" in problems[0])
            # Committed dictionaries are not cleared when the RTFs are not all here.
            self.assertTrue((folder / "dictionaries" / "1y" / "kept.csv").exists())


if __name__ == "__main__":
    unittest.main()
