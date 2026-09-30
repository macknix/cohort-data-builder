/* Everything the views read and write, and the small helpers over it.

   Imports nothing, so it can never take part in a cycle. Touches no DOM. */

export const LEVEL_UNRECORDED = -1;   // dictionary records no measurement level
export const DRAG_MIME = "application/x-survey-merge-variable";

export const state = {
  catalogue: [],     // data/datasets.json: every dataset on the site
  manifest: null,    // data/<key>/manifest.json: the one being browsed
  vars: [],          // [name, label, fileIdx, waveIdx, levelIdx]
  dictCache: new Map(),
  query: "",
  waveFilter: null,  // wave index, or null
  fileFilter: null,  // file index, or null
  levelFilter: null, // measurement level index, LEVEL_UNRECORDED, or null
  // The topic filter: items {kind: "d"|"t", i} into the lists below, combined
  // by topicMode ("any" or "all"). See topics.js.
  topicSel: [],
  topicMode: "any",
  gridExpanded: new Set(),  // domains opened in the grid
  tally: null,       // counts from the last pass, for buttons and grid
  topics: [],        // [{id, label, description, domain}] across all domains
  domains: [],       // manifest.topics.domains
  levelCounts: new Map(),
  matches: [],
  shown: 200,        // rows drawn; "show more" raises it
  expanded: new Set(),   // rows opened in place, by "<fileIndex>:<name>"
  allValues: new Set(),  // opened rows showing every value label
  labelIndex: new Map(), // normalised label -> rows, for "same label"
  // What the download will contain, in the order it was picked:
  // {name, label, file, wave, column}, where `column` is the output name and
  // the only part that may be edited. Kept per dataset.
  bundle: [],
  // The topics grid starts open where there is room for it beside the list,
  // closed on a phone; after that it stays however it was left.
  options: { languages: ["r", "python"], missingToNa: true, minConf: 50,
             gridOpen: typeof matchMedia === "function" &&
               matchMedia("(min-width: 900px) and (min-height: 700px)").matches,
             gridShade: "row", outputFormat: "csv" },
  templates: null,   // data/templates.json, fetched at first download
  view: "search",
};

/* Storage is namespaced by dataset: a selection only makes sense against the
   dataset it was made in. */
export const storeKey = (name, key = state.manifest?.key) =>
  `survey-merge:${key || "_"}:${name}`;

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// NOMINAL -> Nominal. The dictionaries shout; the interface doesn't need to.
export const levelName = (i) => i === LEVEL_UNRECORDED
  ? "Unrecorded"
  : ((state.manifest.levels || [])[i] || "?").replace(/^(.)(.*)$/,
      (_, a, b) => a + b.toLowerCase());

export const capitalise = (s) => String(s).replace(/^./, (c) => c.toUpperCase());

export const waveKeys = () => state.manifest.wave.list.map((w) => w.key);
export const waveLabel = (key) =>
  (state.manifest.wave.list.find((w) => w.key === key) || {}).label || "";

/* What a dragged row carries. */
export function rowPayload(row) {
  const file = state.manifest.files[row[2]];
  return { name: row[0], label: row[1] || "", file: file ? file.name : "",
           wave: waveKeys()[row[3]] };
}

export function highlight(text, term) {
  const t = String(text ?? "");
  if (!term) return esc(t);
  const i = t.toLowerCase().indexOf(term.toLowerCase());
  if (i < 0) return esc(t);
  return esc(t.slice(0, i)) + "<mark>" + esc(t.slice(i, i + term.length)) +
         "</mark>" + esc(t.slice(i + term.length));
}

/* A row's topics at or above the confidence threshold, as [topicIndex,
   percent] pairs, highest first. Rows carry them flat: [t, pct, t, pct, ...]. */
export function rowTopics(row, min = state.options.minConf) {
  const flat = row[5];
  if (!flat) return [];
  const out = [];
  for (let i = 0; i < flat.length; i += 2) if (flat[i + 1] >= min) out.push([flat[i], flat[i + 1]]);
  return out;
}

/* The flattened topic list for the dataset in view. */
export function indexTopics() {
  state.domains = state.manifest.topics?.domains || [];
  state.topics = state.domains.flatMap((d, di) =>
    d.topics.map((t) => ({ ...t, domain: di })));
}

export const isIdentifier = (name) =>
  String(name).toLowerCase() === String(state.manifest?.identifier || "").toLowerCase();
