/* Turning a selection into a downloadable project.

   Almost nothing here is written in JavaScript: the loaders and the merge
   logic are templates under templates/ in the repository, reviewed as R and
   as Python. This fills in the selection, the missing-value codes and the
   README, and zips the result. Loaded on demand — see download() in
   basket.js. */

import { describeNa, loadDict } from "./data.js";
import { zip } from "./zip.js";

/* Anything from a dictionary can contain anything, so every string that lands
   inside a quoted literal is escaped for it. Both languages accept the same
   escapes for what matters here. */
const quote = (s) => `"${String(s ?? "")
  .replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r?\n/g, " ")}"`;

const fill = (template, values) =>
  template.replace(/\{\{(\w+)\}\}/g, (whole, key) => (key in values ? values[key] : whole));

const num = (x) => String(x);

/* ── The selection, in each language ─────────────────────────────────── */

function byFile(bundle) {
  const out = new Map();
  for (const b of bundle) {
    if (!out.has(b.file)) out.set(b.file, []);
    out.get(b.file).push(b);
  }
  return out;
}

function rSelection(groups) {
  return [...groups].map(([file, items]) => `  ${quote(file)} = c(\n` +
    items.map((b) => `    ${quote(b.column)} = ${quote(b.name)}`).join(",\n") +
    "\n  )").join(",\n");
}

function pySelection(groups) {
  return [...groups].map(([file, items]) => `    ${quote(file)}: {\n` +
    items.map((b) => `        ${quote(b.column)}: ${quote(b.name)},`).join("\n") +
    "\n    },").join("\n");
}

// Columns with codes to replace: some carry only codes kept as answers.
const hasCodes = (n) => n && (n.values.length || n.ranges.length);

function rCodes(bundle, na) {
  return bundle.filter((b) => hasCodes(na.get(b))).map((b) => {
    const { values, ranges } = na.get(b);
    const v = values.length ? `c(${values.map(num).join(", ")})` : "numeric(0)";
    const r = ranges.map(([lo, hi]) =>
      `c(${lo === null ? "NA" : num(lo)}, ${hi === null ? "NA" : num(hi)})`).join(", ");
    return `  ${quote(b.column)} = list(values = ${v}, ranges = list(${r}))`;
  }).join(",\n");
}

function pyCodes(bundle, na) {
  return bundle.filter((b) => hasCodes(na.get(b))).map((b) => {
    const { values, ranges } = na.get(b);
    const r = ranges.map(([lo, hi]) =>
      `[${lo === null ? "None" : num(lo)}, ${hi === null ? "None" : num(hi)}]`).join(", ");
    return `    ${quote(b.column)}: {"values": [${values.map(num).join(", ")}], "ranges": [${r}]},`;
  }).join("\n");
}

/* ── Labels, for Stata and SPSS output ─────────────────────────────── */

export const FORMATS = {
  csv: { ext: "csv", name: "CSV" },
  dta: { ext: "dta", name: "Stata" },
  sav: { ext: "sav", name: "SPSS" },
};

/* A column's value labels as [code, label] pairs, or null. Only whole-number
   codes: Stata cannot label anything else, and a set with any fraction in it
   is not a coding scheme. One label per code, the first the dictionary gives. */
function codeLabels(entry) {
  const out = new Map();
  for (const v of entry?.values || []) {
    const x = Number(v.value);
    if (!Number.isFinite(x) || !Number.isInteger(x)) return null;
    if (!out.has(x)) out.set(x, String(v.label ?? ""));
  }
  return out.size ? [...out] : null;
}

function rLabels(bundle, entries, identifier) {
  return [`  ${quote(identifier)} = "Identifier: every file is merged on this"`,
    ...bundle.map((b) => `  ${quote(b.column)} = ${quote(entries.get(b)?.label || b.label || b.name)}`)]
    .join(",\n");
}

function pyLabels(bundle, entries, identifier) {
  return [`    ${quote(identifier)}: "Identifier: every file is merged on this",`,
    ...bundle.map((b) => `    ${quote(b.column)}: ${quote(entries.get(b)?.label || b.label || b.name)},`)]
    .join("\n");
}

function rValueLabels(bundle, entries) {
  return bundle.map((b) => [b, codeLabels(entries.get(b))]).filter(([, c]) => c)
    .map(([b, c]) => `  ${quote(b.column)} = c(${c.map(([x, l]) => `${quote(l)} = ${x}`).join(", ")})`)
    .join(",\n");
}

function pyValueLabels(bundle, entries) {
  return bundle.map((b) => [b, codeLabels(entries.get(b))]).filter(([, c]) => c)
    .map(([b, c]) => `    ${quote(b.column)}: {${c.map(([x, l]) => `${x}: ${quote(l)}`).join(", ")}},`)
    .join("\n");
}

/* ── The codebook ────────────────────────────────────────────────────── */

const csvCell = (s) => {
  const t = String(s ?? "");
  return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};

function codebook(bundle, entries, na, identifier, topicLabels) {
  // negative_kept: negative codes that are answers, not missing, so never
  // replaced ("-1=Dislike").
  const rows = [["column", "variable", "file", "wave", "label", "missing_codes", "negative_kept",
                 "value_labels", "topics"]];
  rows.push([identifier, identifier, "", "", "Identifier: every file is merged on this", "", "", "", ""]);
  for (const b of bundle) {
    const entry = entries.get(b);
    rows.push([
      b.column, b.name, b.file, b.wave, entry?.label || b.label,
      describeNa(na.get(b)),
      (na.get(b)?.kept || []).map(([x, l]) => `${x}=${l}`).join("; "),
      (entry?.values || []).map((v) => `${v.value}=${v.label}`).join("; "),
      (entry?.topics || []).map(([id, c]) => `${topicLabels.get(id) || id} (${c.toFixed(2)})`).join("; "),
    ]);
  }
  return rows.map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

/* ── The README ──────────────────────────────────────────────────────── */

function runSteps(languages, project) {
  const steps = [];
  if (languages.includes("r")) {
    steps.push(`**R.** Open \`${project}.Rproj\` in RStudio and source \`R/merge.R\`, or run
\`Rscript R/merge.R\` from this folder. Reading \`.tab\` files needs only base R;
\`.dta\` and \`.sav\` files need \`install.packages("haven")\`.`);
  }
  if (languages.includes("python")) {
    steps.push(`**Python.** \`pip install -r python/requirements.txt\`, then
\`python python/merge.py\`. \`pyreadstat\` is only needed for \`.sav\` files.`);
  }
  return steps.join("\n\n");
}

function contents(languages, project) {
  const lines = ["    README.md          this file",
                 "    codebook.csv       what every output column is",
                 "    data/              where the data files go",
                 "    output/            created on the first run"];
  if (languages.includes("r")) {
    lines.push(`    ${project}.Rproj`,
               "    R/load_data.R      finds and reads data files; the read call follows the extension",
               "    R/merge.R          your selection and the merge: run this");
  }
  if (languages.includes("python")) {
    lines.push("    python/load_data.py  finds and reads data files; the read call follows the extension",
               "    python/merge.py      your selection and the merge: run this",
               "    python/requirements.txt");
  }
  return lines.join("\n");
}

/* ── Everything together ─────────────────────────────────────────────── */

export async function build(bundle, manifest, templates, options) {
  const today = new Date().toISOString().slice(0, 10);
  const project = `${manifest.key}-merge-${today}`;
  const { languages, missingToNa } = options;
  const format = FORMATS[options.outputFormat] ? options.outputFormat : "csv";

  // Each file's dictionary, for the missing codes and the codebook.
  const groups = byFile(bundle);
  const dicts = new Map(await Promise.all(
    [...groups.keys()].map(async (f) => [f, await loadDict(f)])));
  const entries = new Map(bundle.map((b) => [b,
    dicts.get(b.file).variables.find((v) => v.variable === b.name)]));
  const na = new Map(bundle.map((b) => [b, entries.get(b)?.na || null]));

  const fileInfo = new Map(manifest.files.map((f) => [f.name, f]));
  const fileList = [...groups.keys()].map((f) => {
    const info = fileInfo.get(f) || {};
    return `- \`${f}\`${info.description ? ` — ${info.description}` : ""} (${info.wave || "?"})`;
  }).join("\n");

  const common = {
    dataset: manifest.name,
    full_name: manifest.fullName,
    created: today,
    identifier: manifest.identifier,
    ukds_url: manifest.ukdsUrl || "the UK Data Service",
    files: fileList,
  };

  const files = [];
  const add = (path, text) => files.push([`${project}/${path}`, text]);

  add("README.md", fill(templates["README.md"], {
    ...common,
    count: `${bundle.length} variable${bundle.length === 1 ? "" : "s"}`,
    ext: FORMATS[format].ext,
    format_note: format === "csv"
      ? " CSV has no room for labels: `codebook.csv` has them."
      : ` A ${FORMATS[format].name} file, with each column's label and value labels from the ` +
        "data dictionary. To get a different file type, change `OUTPUT_FORMAT` at the top " +
        "of the merge script (\"csv\", \"dta\" or \"sav\").",
    languages: languages.length === 2
      ? "The same merge is included in R and in Python; use whichever you prefer."
      : `The merge is written in ${languages[0] === "r" ? "R" : "Python"}.`,
    missing_note: missingToNa
      ? "**Missing-value codes are converted to NA.** Each variable's declared missing " +
        "codes, and any other negative code labelled as missing (\"Not known\", " +
        "\"Refused\"…), are replaced with NA — `codebook.csv` lists exactly which. A " +
        "negative code with any other label is a real answer and is kept (its " +
        "`negative_kept` column). Set `MISSING_TO_NA` to false at the top of the merge " +
        "script to keep them all."
      : "**Missing-value codes are kept as deposited.** Set `MISSING_TO_NA` to true at " +
        "the top of the merge script to replace them with NA — `codebook.csv` lists " +
        "which codes that would replace.",
    run: runSteps(languages, project),
    contents: contents(languages, project),
  }));
  const topicLabels = new Map((manifest.topics?.domains || [])
    .flatMap((d) => d.topics.map((t) => [t.id, t.label])));
  add("codebook.csv", codebook(bundle, entries, na, manifest.identifier, topicLabels));
  add("data/README.md", fill(templates["data-README.md"], common));

  if (languages.includes("r")) {
    add(`${project}.Rproj`, templates["project.Rproj"]);
    add("R/load_data.R", templates["r/load_data.R"]);
    add("R/merge.R", fill(templates["r/merge.R"], {
      ...common,
      missing_to_na: missingToNa ? "TRUE" : "FALSE",
      output_format: format,
      labels: rLabels(bundle, entries, manifest.identifier),
      value_labels: rValueLabels(bundle, entries),
      selection: rSelection(groups),
      missing_codes: rCodes(bundle, na),
    }));
  }
  if (languages.includes("python")) {
    add("python/load_data.py", templates["python/load_data.py"]);
    add("python/requirements.txt", templates["python/requirements.txt"]);
    add("python/merge.py", fill(templates["python/merge.py"], {
      ...common,
      missing_to_na: missingToNa ? "True" : "False",
      output_format: format,
      labels: pyLabels(bundle, entries, manifest.identifier),
      value_labels: pyValueLabels(bundle, entries),
      selection: pySelection(groups),
      missing_codes: pyCodes(bundle, na),
    }));
  }

  return { name: `${project}.zip`, blob: await zip(files), files };
}
