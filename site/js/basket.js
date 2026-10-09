/* The selection: what you picked, what the output will contain, and the
   download.

   The list pane is what you picked up; the detail pane is the output CSV's
   columns. They are not the same list twice: the second is where a name
   collision between two files becomes visible — two files both calling
   something `sex` is the normal case — and it is the one place a column can
   be renamed. */

import { $, $$ } from "./dom.js";
import { DRAG_MIME, esc, isIdentifier, state, storeKey, waveKeys } from "./state.js";
import { renderSpine } from "./spine.js";
import { onShow } from "./views.js";

/* What else to redraw when the selection changes. Set by boot.js, so this
   module does not import the search view back. */
let notify = () => {};
export const onChange = (fn) => { notify = fn; };
let openFile = () => {};
export const onOpenFile = (fn) => { openFile = fn; };

const keyOf = (b) => `${b.file}:${b.name}`;

/* Asked once per row drawn and per result checked, so with thousands
   selected it is a set lookup, not a scan. The bundle only ever grows in
   place (push) or is replaced, so its identity and length say whether the
   set still matches it. */
let index = { of: null, n: -1, keys: new Set() };
export function has(file, name) {
  if (index.of !== state.bundle || index.n !== state.bundle.length) {
    index = { of: state.bundle, n: state.bundle.length, keys: new Set(state.bundle.map(keyOf)) };
  }
  return index.keys.has(`${file}:${name}`);
}

/* The intersection of a valid R name, a valid Python identifier-ish column
   and a CSV header that survives any tool. */
const NAME_OK = /^[A-Za-z][A-Za-z0-9_.]*$/;
export const sanitiseColumn = (s) => String(s || "")
  .replace(/[^A-Za-z0-9_.]/g, "_")
  .replace(/^[^A-Za-z]+/, "");

/* The variable's own name, qualified by wave only if that would collide. */
function defaultColumn(name, wave, taken) {
  const base = sanitiseColumn(name) || "var";
  if (!taken.has(base.toLowerCase())) return base;
  const qualified = sanitiseColumn(`${base}_${wave}`);
  if (!taken.has(qualified.toLowerCase())) return qualified;
  for (let n = 2; ; n++) {
    const candidate = `${qualified}_${n}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}

/* Every output column already claimed, lower-cased because a column that
   differs only by case is a collision in Stata, SPSS and most people's heads.
   The identifier is here too: it is column one of every output. */
function taken(except) {
  const out = new Set([String(state.manifest.identifier).toLowerCase()]);
  for (const b of state.bundle) if (keyOf(b) !== except) out.add(b.column.toLowerCase());
  return out;
}

/* ── Adding and removing ─────────────────────────────────────────────── */

/* Put one variable in the bundle without saving or redrawing. Returns why it
   could not go in, "" if it went in, or null if it was already there. */
function put({ name, label, file, wave }) {
  if (!name || !file || has(file, name)) return null;
  if (isIdentifier(name)) return `${name} is already in every download: it is what the files are merged on.`;
  const known = state.manifest.files.find((f) => f.name === file);
  if (!known) return `${file} is not in this cohort.`;
  if (!known.hasId) return `${file} has no ${state.manifest.identifier} column, so it cannot be merged.`;
  state.bundle.push({ name, label: label || "", file, wave: wave || known.wave,
                      column: defaultColumn(name, wave || known.wave, taken()) });
  return "";
}

export function add(item) {
  const why = put(item);
  if (why) say(why);
  if (why !== "") return false;
  save(); render();
  return true;
}

/* Many at once, saved and redrawn once: a range or a whole result list.
   Returns how many went in. */
export function addMany(items) {
  let added = 0;
  for (const item of items) if (put(item) === "") added++;
  if (added) { save(); render(); }
  return added;
}

export function remove(key) {
  state.bundle = state.bundle.filter((b) => keyOf(b) !== key);
  save(); render();
}

/* Returns how many came out. */
export function removeMany(items) {
  const keys = new Set(items.map(keyOf));
  const before = state.bundle.length;
  state.bundle = state.bundle.filter((b) => !keys.has(keyOf(b)));
  const removed = before - state.bundle.length;
  if (removed) { save(); render(); }
  return removed;
}

export function clear() {
  state.bundle = [];
  save(); render();
}

export function toggle(item) {
  return has(item.file, item.name) ? remove(`${item.file}:${item.name}`) : add(item);
}

/* ── Persistence ───────────────────────────────────────────────────────
   The selection is kept per dataset; the options once for everyone. */

function save() {
  try { localStorage.setItem(storeKey("selection"), JSON.stringify(state.bundle)); }
  catch { /* private browsing: the selection just won't persist */ }
}

export function saveOptions() {
  try { localStorage.setItem(storeKey("options", "_site"), JSON.stringify(state.options)); }
  catch { /* as above */ }
}

export function restoreOptions() {
  try {
    const saved = JSON.parse(localStorage.getItem(storeKey("options", "_site")) || "null");
    if (saved && Array.isArray(saved.languages)) {
      state.options.languages = saved.languages.filter((l) => l === "r" || l === "python");
      if (!state.options.languages.length) state.options.languages = ["r", "python"];
      state.options.missingToNa = saved.missingToNa !== false;
      if ([30, 50, 70, 90].includes(saved.minConf)) state.options.minConf = saved.minConf;
      state.options.gridShade = saved.gridShade === "abs" ? "abs" : "row";
      if (["csv", "dta", "sav"].includes(saved.outputFormat)) state.options.outputFormat = saved.outputFormat;
      state.options.panelOpen = saved.panelOpen === true;
      state.options.panelGroup = saved.panelGroup === "file" ? "file" : "wave";
    }
  } catch { /* defaults */ }
}

/* A saved selection can outlive what it names when the site is rebuilt, so
   anything that no longer resolves is dropped rather than failing later. */
export function restore() {
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem(storeKey("selection")) || "[]"); }
  catch { saved = []; }
  const exists = new Set(state.vars.map((r) => `${state.manifest.files[r[2]].name}:${r[0]}`));
  state.bundle = [];
  const claimed = new Set([String(state.manifest.identifier).toLowerCase()]);
  for (const b of Array.isArray(saved) ? saved : []) {
    if (!b || !exists.has(`${b.file}:${b.name}`) || isIdentifier(b.name)) continue;
    const column = NAME_OK.test(b.column || "") && !claimed.has(b.column.toLowerCase())
      ? b.column : defaultColumn(b.name, b.wave, claimed);
    claimed.add(column.toLowerCase());
    state.bundle.push({ ...b, column });
  }
}

/* ── Problems that block the download ─────────────────────────────────── */

/* What each output file type allows in a column name, beyond NAME_OK. */
const FORMAT_RULES = {
  csv: () => null,
  dta: (name) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)
    ? `Stata names use only letters, digits and _: try ${name.replace(/[^A-Za-z0-9_]/g, "_")}.`
    : name.length > 32 ? "Stata names are at most 32 characters." : null,
  sav: (name) => name.length > 64 ? "SPSS names are at most 64 characters."
    : name.endsWith(".") ? "SPSS names cannot end with a dot." : null,
};

export function problems() {
  const out = new Map();
  const seen = new Map([[String(state.manifest.identifier).toLowerCase(), null]]);
  const rule = FORMAT_RULES[state.options.outputFormat] || FORMAT_RULES.csv;
  for (const b of state.bundle) {
    if (!NAME_OK.test(b.column || "")) {
      out.set(keyOf(b), "Must start with a letter and use only letters, digits, _ or .");
      continue;
    }
    const formatProblem = rule(b.column);
    if (formatProblem) {
      out.set(keyOf(b), formatProblem);
      continue;
    }
    const lower = b.column.toLowerCase();
    if (seen.has(lower)) {
      const other = seen.get(lower);
      const msg = other === null
        ? `${b.column} is the identifier's name; the column would overwrite it.`
        : `Two columns would both be called ${b.column}.`;
      out.set(keyOf(b), msg);
      if (other) out.set(other, msg);
      continue;
    }
    seen.set(lower, keyOf(b));
  }
  return out;
}

/* ── Rendering ───────────────────────────────────────────────────────── */

/* The Selection view's panes are drawn only while it is showing, and when
   it is switched to: with thousands selected they are the slowest thing on
   the page, and every click in the list would otherwise redraw them unseen. */
export function render() {
  notify();
  const n = state.bundle.length;
  $("#basket-tally").textContent = n;
  $("#basket-tally").hidden = n === 0;
  if (state.view !== "basket") return;
  renderList();
  renderDetail();
  renderSpine();
}
onShow("basket", () => { renderList(); renderDetail(); });

function renderList() {
  const n = state.bundle.length;
  $("#basket-clear").hidden = n === 0;
  const count = $("#basket-count");
  if (!count.classList.contains("is-saying")) {
    count.innerHTML = n ? `<strong>${n}</strong> variable${n === 1 ? "" : "s"}` : "Nothing selected yet";
  }

  const keys = waveKeys();
  const sorted = [...state.bundle].sort((a, b) =>
    keys.indexOf(a.wave) - keys.indexOf(b.wave) || a.file.localeCompare(b.file));
  $("#basket-list").innerHTML = sorted.map((b) => `
    <li class="pickable">
      <button class="add is-in basket-x" data-remove="${esc(keyOf(b))}"
              aria-label="Remove ${esc(b.name)}" title="Remove"><span class="add-yes">✓</span><span class="add-no">✕</span></button>
      <span class="row" style="cursor:default">
        <span class="row-top">
          <span class="row-name">${esc(b.name)}</span>
          <span class="row-wave">${esc(b.wave)}</span>
        </span>
        <span class="row-label">${esc(b.label || "no label")}</span>
        <span class="row-file">${esc(b.file)}</span>
      </span></li>`).join("");
}

function renderDetail() {
  const el = $("#basket-detail");
  const n = state.bundle.length;
  const m = state.manifest;

  if (!n) {
    el.innerHTML = `<div class="empty">
      <h2>Build a merge script</h2>
      <p>Pick variables in <strong>Variables</strong>, then download a small R or
        Python project that reads them from your own copy of the ${esc(m.name)} data
        and merges them into one CSV, one row per person.</p>
      <p>No study data is in the download or on this site: only the data
        dictionaries, which describe what each variable is.</p>
      <p class="empty-hint">Drag a row onto the Selection tab, or use the ＋ beside it.</p>
    </div>`;
    return;
  }

  const bad = problems();
  const files = [...new Set(state.bundle.map((b) => b.file))];
  const byFile = new Map(m.files.map((f) => [f.name, f]));
  const keys = waveKeys();
  files.sort((a, b) => keys.indexOf(byFile.get(a).wave) - keys.indexOf(byFile.get(b).wave) ||
    a.localeCompare(b));
  const { languages, missingToNa } = state.options;
  const format = state.options.outputFormat;
  const ext = { csv: "csv", dta: "dta", sav: "sav" }[format] || "csv";
  const dotted = format === "dta" && state.bundle.some((b) => /[^A-Za-z0-9_]/.test(b.column));

  el.innerHTML = `
    <div class="detail-head">
      <div class="detail-eyebrow">${esc(m.name)} · ${n} variable${n === 1 ? "" : "s"} from ${files.length} file${files.length === 1 ? "" : "s"}</div>
      <h1 class="detail-name">output/merged.${ext}</h1>
      <p class="detail-label">One row per person, joined on <code>${esc(m.identifier)}</code>.
        A file with several rows per person is written to its own file instead.</p>
    </div>

    ${bad.size ? `<div class="warn"><span>⚠</span><div>
      <strong>${bad.size} column name${bad.size === 1 ? " needs" : "s need"} changing</strong>
      before downloading; each says why below.${dotted
        ? ` <button class="link-btn" id="fix-dots">Replace every . with _</button>` : ""}</div></div>` : ""}

    <h2 class="section-title">Columns</h2>
    <p class="note">In the order they are written. Rename any of them here.</p>
    <ol class="cols">
      <li class="col-row is-fixed">
        <span class="col-kind col-kind-id" title="The identifier">·</span>
        <span class="col-body"><span class="col-name">${esc(m.identifier)}</span>
          <span class="col-note">always included — the key the files are merged on</span></span>
      </li>
      ${files.flatMap((f) => state.bundle.filter((b) => b.file === f)).map((b) => colRow(b, bad)).join("")}
    </ol>

    <h2 class="section-title">Data files it needs</h2>
    <ul class="linklist">${files.map((f) => `<li><button data-file="${esc(f)}">
        <span class="ll-name">${esc(f)}</span>
        <span class="ll-desc">${esc(byFile.get(f).description || "")}</span>
        <span class="ll-meta">${esc(byFile.get(f).wave)}</span>
      </button></li>`).join("")}</ul>
    <p class="note">Put them all in one <code>data/</code> folder, in any format (<code>.tab</code>, <code>.dta</code>, <code>.sav</code>): the scripts pick the read call from the extension.${m.ukdsUrl
        ? ` Download them from the <a href="${esc(m.ukdsUrl)}" target="_blank" rel="noopener">UK Data Service</a>.` : ""}</p>

    <h2 class="section-title">Download</h2>
    <div class="options">
      <div class="option-row">
        <span class="option-name">Language</span>
        <label><input type="checkbox" data-lang="r" ${languages.includes("r") ? "checked" : ""}> R</label>
        <label><input type="checkbox" data-lang="python" ${languages.includes("python") ? "checked" : ""}> Python</label>
      </div>
      <div class="option-row">
        <span class="option-name">Output file</span>
        <label><input type="radio" name="opt-format" value="csv" ${format === "csv" ? "checked" : ""}> CSV</label>
        <label><input type="radio" name="opt-format" value="dta" ${format === "dta" ? "checked" : ""}> Stata (.dta)</label>
        <label><input type="radio" name="opt-format" value="sav" ${format === "sav" ? "checked" : ""}> SPSS (.sav)</label>
        <p class="option-help">${format === "csv"
          ? "Plain text that opens anywhere. Labels go in <code>codebook.csv</code> alongside it."
          : `Carries each column's label and value labels from the data dictionary. Needs
             <code>haven</code> in R${format === "sav" ? " and <code>pyreadstat</code> in Python" : ""}.`}</p>
      </div>
      <div class="option-row">
        <span class="option-name">Missing codes</span>
        <label><input type="checkbox" id="opt-na" ${missingToNa ? "checked" : ""}> Convert to NA</label>
        <p class="option-help">Replaces each variable's declared missing-value codes, and any negative code with a value label, with NA. Off keeps the codes as deposited. Either way it is one setting at the top of the script, and <code>codebook.csv</code> lists the codes.</p>
      </div>
    </div>
    <div class="detail-actions">
      <button class="btn btn-primary" id="basket-download">Download</button>
    </div>
    <p class="draft-status" id="basket-status" role="status"></p>`;

  const button = $("#basket-download");
  button.disabled = bad.size > 0 || !languages.length;
  button.textContent = `Download ${languages.map((l) => (l === "r" ? "R" : "Python")).join(" + ") || "…"} code`;
  button.addEventListener("click", download);

  $$("#basket-detail [data-lang]").forEach((box) => box.addEventListener("change", () => {
    const on = $$("#basket-detail [data-lang]").filter((b) => b.checked).map((b) => b.dataset.lang);
    state.options.languages = on;
    saveOptions(); renderDetail();
  }));
  $("#opt-na").addEventListener("change", (e) => {
    state.options.missingToNa = e.target.checked;
    saveOptions();
  });
  $$("#basket-detail [name=opt-format]").forEach((r) => r.addEventListener("change", () => {
    state.options.outputFormat = r.value;
    saveOptions(); renderDetail();
  }));
  $("#fix-dots")?.addEventListener("click", () => {
    const taken = new Set([String(m.identifier).toLowerCase()]);
    for (const b of state.bundle) {
      let name = b.column.replace(/[^A-Za-z0-9_]/g, "_");
      for (let i = 2; taken.has(name.toLowerCase()); i++) name = `${b.column.replace(/[^A-Za-z0-9_]/g, "_")}_${i}`;
      b.column = name;
      taken.add(name.toLowerCase());
    }
    save(); render();
  });

  $$("#basket-detail [data-rename]").forEach((input) => {
    // Committed on blur or Enter, not per keystroke: a re-render replaces the
    // input being typed into.
    const commit = () => {
      const item = state.bundle.find((b) => keyOf(b) === input.dataset.rename);
      const next = sanitiseColumn(input.value.trim());
      if (!item || next === item.column) return;
      item.column = next;
      save(); render();
    };
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    });
  });
  $$("#basket-detail [data-file]").forEach((b) =>
    b.addEventListener("click", () => openFile(b.dataset.file)));
}

function colRow(b, bad) {
  const problem = bad.get(keyOf(b));
  return `<li class="col-row${problem ? " is-bad" : ""}">
    <span class="col-kind col-kind-raw" title="${esc(b.wave)}">${esc(b.wave)}</span>
    <span class="col-body">
      <input class="col-input" type="text" value="${esc(b.column)}"
             data-rename="${esc(keyOf(b))}" spellcheck="false" autocomplete="off"
             aria-label="Output column name for ${esc(b.name)}"
             aria-invalid="${problem ? "true" : "false"}">
      <span class="col-note">${esc(b.label || "no label")} ·
        ${b.column === b.name ? "" : `<code>${esc(b.name)}</code> in `}<code>${esc(b.file)}</code></span>
      ${problem ? `<span class="col-problem">${esc(problem)}</span>` : ""}
    </span>
  </li>`;
}

/* ── Messages ─────────────────────────────────────────────────────────
   The status line only exists while the detail pane is drawn, so the count
   line in the list pane is the fallback: a refusal nobody sees is
   indistinguishable from a drop that did nothing. */
let sayTimer;
function say(msg) {
  const el = $("#basket-status") || $("#basket-count");
  if (!el) return;
  const restoreHtml = el.id === "basket-count" ? el.innerHTML : "";
  el.textContent = msg;
  el.classList.add("is-saying");
  clearTimeout(sayTimer);
  sayTimer = setTimeout(() => {
    el.classList.remove("is-saying");
    if (restoreHtml) el.innerHTML = restoreHtml; else el.textContent = "";
  }, 8000);
}

/* ── Downloading ─────────────────────────────────────────────────────── */

async function download() {
  if (!state.bundle.length || problems().size || !state.options.languages.length) return;
  const button = $("#basket-download");
  button.disabled = true;
  say("Packaging…");
  try {
    // Loaded only now: most visitors never download anything.
    const [{ build }, templates] = await Promise.all([
      import("./codegen.js"),
      state.templates || fetch("data/templates.json").then((r) => {
        if (!r.ok) throw new Error("templates.json is missing — rebuild the site");
        return r.json();
      }),
    ]);
    state.templates = templates;
    const { name, blob } = await build(state.bundle, state.manifest, templates, state.options);

    const url = URL.createObjectURL(blob);
    const link = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    say(`${name} — ${(blob.size / 1024).toFixed(0)} KB. Its README says what to do next.`);
  } catch (err) {
    console.error(err);
    say(`Could not build the download: ${err.message}`);
  } finally {
    const again = $("#basket-download");
    if (again) again.disabled = !state.bundle.length || problems().size > 0;
  }
}

/* ── Wiring ──────────────────────────────────────────────────────────── */

export function wire() {
  $("#basket-clear").addEventListener("click", clear);
  $("#basket-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove]");
    if (btn) remove(btn.dataset.remove);
  });

  /* Drag and drop. The pane is a target while you are in this view, and the
     tab is a target from the other, which is the only way a drag from the
     search list can reach it. */
  const targets = [$("#basket-drop"), $('.view-tab[data-view="basket"]')];
  const accepts = (e) => [...(e.dataTransfer?.types || [])].includes(DRAG_MIME);

  document.addEventListener("dragstart", (e) => {
    const src = e.target.closest?.("[data-drag]");
    if (!src) return;
    e.dataTransfer.setData(DRAG_MIME, src.dataset.drag);
    e.dataTransfer.setData("text/plain", JSON.parse(src.dataset.drag).name);
    e.dataTransfer.effectAllowed = "copy";
    document.body.classList.add("is-dragging-var");
  });
  document.addEventListener("dragend", () => {
    document.body.classList.remove("is-dragging-var");
    targets.forEach((t) => t.classList.remove("is-dropping"));
  });

  for (const target of targets) {
    let depth = 0;
    target.addEventListener("dragenter", (e) => {
      if (!accepts(e)) return;
      e.preventDefault(); depth++; target.classList.add("is-dropping");
    });
    target.addEventListener("dragover", (e) => {
      if (!accepts(e)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "copy";
    });
    target.addEventListener("dragleave", () => {
      if (--depth <= 0) { depth = 0; target.classList.remove("is-dropping"); }
    });
    target.addEventListener("drop", (e) => {
      if (!accepts(e)) return;
      e.preventDefault(); depth = 0;
      target.classList.remove("is-dropping");
      try { add(JSON.parse(e.dataTransfer.getData(DRAG_MIME))); } catch { /* not ours */ }
    });
  }
}
