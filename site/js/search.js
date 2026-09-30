/* The variables: finding them, listing them, and opening one in place.

   The list is built for scanning. Each row carries what decides whether a
   variable is worth a look — its name, its label in full, its sweep and its
   topics — and nothing else. Everything secondary (value labels, missing
   codes, the file it lives in) opens under the row on a click, a few lines
   rather than a pane, so many variables stay on screen at once.

   The search itself is a substring scan over the index the page already
   holds, so it finds a fragment of a half-remembered name as well as a word
   in a label, and needs no server. */

import { $ } from "./dom.js";
import {
  LEVEL_UNRECORDED, esc, highlight, isIdentifier, levelName,
  rowPayload, rowTopics, state, waveKeys, waveLabel,
} from "./state.js";
import { renderSpine } from "./spine.js";
import { switchView } from "./views.js";
import * as basket from "./basket.js";
import { describeNa, loadDict } from "./data.js";
import * as topics from "./topics.js";

const PAGE = 200;               // rows drawn at a time; "show more" draws the next
const VALUES_SHOWN = 8;         // value labels before "+ N more"
const ALSO_MAX = 10;            // other sweeps listed under "Also asked at"
const ALSO_GROUP_MAX = 40;      // a label shared this widely is boilerplate, not a question

const keyOf = (row) => `${row[2]}:${row[0]}`;

/* ── Searching ───────────────────────────────────────────────────────── */

/* A change of filter starts from the top of the list again; a change that
   only redraws (something added to the selection) keeps your place. */
export function runSearch({ keepPlace = false } = {}) {
  const q = state.query.trim().toLowerCase();
  const out = [];
  // One pass feeds everything. Level counts leave out the level filter, so
  // each option says what choosing it would give; the topic rows leave out
  // the sweep and topic filters, being where those are chosen.
  const levels = new Map();
  const tally = topics.newTally();
  const tagged = state.domains.length > 0;
  for (const row of state.vars) {
    if (state.fileFilter !== null && row[2] !== state.fileFilter) continue;
    if (q && !row[0].toLowerCase().includes(q) && !row[1].toLowerCase().includes(q)) continue;
    const level = row[4] ?? LEVEL_UNRECORDED;
    const levelOk = state.levelFilter === null || level === state.levelFilter;
    const waveOk = state.waveFilter === null || row[3] === state.waveFilter;
    let topicOk = true;
    if (tagged) {
      const ts = rowTopics(row).map(([t]) => t);
      const ds = new Set(ts.map((t) => state.topics[t].domain));
      topicOk = topics.passes(topics.matched(ts, ds));
      if (levelOk) topics.countGrid(tally, ts, ds, row[3]);
    }
    if (!waveOk) continue;
    if (topicOk) levels.set(level, (levels.get(level) || 0) + 1);
    if (levelOk && topicOk) out.push(row);
  }
  state.levelCounts = levels;
  state.tally = tally;
  state.matches = out;
  if (!keepPlace) state.shown = PAGE;

  renderResults();
  renderSpine();
  renderLevelSelect();
  topics.renderGrid();
  renderFilters();
}

/* Measurement level is a refinement, not a way in: a dropdown, with counts. */
function renderLevelSelect() {
  const levels = state.manifest.levels || [];
  const sel = $("#level");
  sel.hidden = !levels.length;
  const total = [...state.levelCounts.values()].reduce((a, b) => a + b, 0);
  const opt = (value, label, n) =>
    `<option value="${value}" ${n || String(state.levelFilter) === value ? "" : "disabled"}>${esc(label)} (${n.toLocaleString()})</option>`;
  sel.innerHTML = `<option value="">Any level (${total.toLocaleString()})</option>` +
    [...levels.keys(), LEVEL_UNRECORDED].map((k) =>
      opt(String(k), levelName(k), state.levelCounts.get(k) || 0)).join("");
  sel.value = state.levelFilter === null ? "" : String(state.levelFilter);
}

function renderFilters() {
  const chips = [];
  const keys = waveKeys();
  if (state.waveFilter !== null) {
    chips.push(`<button class="chip" data-clear="wave" title="Show every ${esc(state.manifest.wave.term)}">${esc(keys[state.waveFilter])} ✕</button>`);
  }
  if (state.fileFilter !== null) {
    chips.push(`<button class="chip" data-clear="file">${esc(state.manifest.files[state.fileFilter].name)} ✕</button>`);
  }
  chips.push(...topics.chips());
  $("#active-filters").innerHTML = chips.join("");
  $("#clear-filters").hidden = !(chips.length || state.query || state.levelFilter !== null);
  const n = state.matches.length;
  $("#result-count").textContent = `${n.toLocaleString()} variable${n === 1 ? "" : "s"}`;
}

/* ── The list ────────────────────────────────────────────────────────── */

/* The control beside a row: ＋ to add, ✓ when added (✕ on hover to remove),
   a fixed ✓ for the identifier, which is in every download already, and a
   blank for a file with no identifier to merge on. */
function addControl(row, file) {
  if (isIdentifier(row[0])) {
    return `<span class="add is-always" title="Included in every download"
      aria-label="${esc(row[0])} is included in every download">✓</span>`;
  }
  if (!file.hasId) return `<span class="add is-none"></span>`;
  const isIn = basket.has(file.name, row[0]);
  return `<button class="add${isIn ? " is-in" : ""}" data-add="${esc(row[0])}"
      data-add-file="${esc(file.name)}" aria-pressed="${isIn}"
      title="${isIn ? "In your selection — click to remove" : "Add to your selection"}"
      aria-label="${isIn ? "Remove" : "Add"} ${esc(row[0])}"
      >${isIn ? '<span class="add-yes">✓</span><span class="add-no">✕</span>' : "＋"}</button>`;
}

function rowHtml(row, i, q, keys) {
  const file = state.manifest.files[row[2]];
  const key = keyOf(row);
  const open = state.expanded.has(key);
  const tags = rowTopics(row).slice(0, 2).map(([t]) =>
    `<span class="topic-chip">${esc(state.topics[t].label)}</span>`).join("");
  return `<li class="vrow${open ? " is-open" : ""}" data-key="${esc(key)}">
    <div class="vrow-main">${addControl(row, file)}
      <button class="vrow-btn" data-i="${i}" aria-expanded="${open}" draggable="true"
          data-drag="${esc(JSON.stringify(rowPayload(row)))}">
        <span class="v-name">${highlight(row[0], q)}</span>
        <span class="v-label">${highlight(row[1] || "No label", q)}</span>
        <span class="v-wave" title="${esc(waveLabel(keys[row[3]]))}">${esc(keys[row[3]])}</span>
        <span class="v-topics">${tags}</span>
        <span class="v-chev" aria-hidden="true">${open ? "▾" : "▸"}</span>
      </button>
    </div>
    ${open ? `<div class="vrow-more" id="more-${esc(key)}">${moreHtml(row)}</div>` : ""}
  </li>`;
}

export function renderResults() {
  const q = state.query.trim();
  const keys = waveKeys();
  const total = state.matches.length;
  const shown = state.matches.slice(0, state.shown);

  if (!total) {
    $("#results").innerHTML = `<li class="vempty">No variables match.
      <button class="link-btn" data-clear-all>Clear the filters</button></li>`;
  } else {
    $("#results").innerHTML =
      `<li class="vhead" aria-hidden="true"><span></span><span>Variable</span><span>Label</span>
         <span>${esc(state.manifest.wave.term)}</span><span>Topics</span><span></span></li>` +
      shown.map((row, i) => rowHtml(row, i, q, keys)).join("");
  }
  const more = $("#more");
  const left = total - shown.length;
  more.hidden = left <= 0;
  if (left > 0) {
    more.innerHTML = `<button class="btn" id="show-more">Show ${Math.min(PAGE, left).toLocaleString()} more</button>
      <span>${shown.length.toLocaleString()} of ${total.toLocaleString()} shown</span>`;
  }
  // Rows open before their dictionary arrived fill in now.
  for (const row of shown) {
    if (state.expanded.has(keyOf(row))) fillMore(row);
  }
}

/* ── A variable, opened ──────────────────────────────────────────────── */

const dictEntry = (row) => {
  const d = state.dictCache.get(`${state.manifest.key}/${state.manifest.files[row[2]].name}`);
  return d ? d.variables.find((v) => v.variable === row[0]) || null : undefined;
};

async function fillMore(row) {
  const key = keyOf(row);
  if (dictEntry(row) !== undefined) return;
  try { await loadDict(state.manifest.files[row[2]].name); } catch { /* shown as missing */ }
  const el = document.getElementById(`more-${key}`);
  if (el && state.expanded.has(key)) el.innerHTML = moreHtml(row);
}

function valuesHtml(row, entry) {
  const key = keyOf(row);
  if (isIdentifier(row[0])) {
    return `<p class="vm-note">The identifier every file is merged on: always the first column of a download.</p>`;
  }
  const values = entry?.values || [];
  if (!values.length) {
    const scale = entry?.measurement === "SCALE";
    return `<p class="vm-note">${scale ? "A continuous measure: no value labels." : "No value labels recorded."}</p>`;
  }
  // Answers first, missing codes after on a quieter line of their own: the
  // dictionaries list the negative sentinels first, but they are the least
  // interesting thing about a variable.
  const na = entry.na;
  const naSet = new Set(na?.values || []);
  const isNa = (x) => naSet.has(x) || (na?.ranges || []).some(([lo, hi]) =>
    (lo === null || x >= lo) && (hi === null || x <= hi));
  const code = (v) => String(v.value).replace(/\.0$/, "");
  const item = (v) => `<li><span class="vm-code">${esc(code(v))}</span> ${esc(v.label)}</li>`;
  const missing = values.filter((v) => { const x = parseFloat(v.value); return !Number.isNaN(x) && isNa(x); });
  const answers = values.filter((v) => !missing.includes(v));
  const all = state.allValues.has(key);
  const list = all ? answers : answers.slice(0, VALUES_SHOWN);
  const rest = answers.length - list.length;
  const toggle = rest > 0
    ? `<li><button class="link-btn" data-values="${esc(key)}">+ ${rest} more</button></li>`
    : all && answers.length > VALUES_SHOWN
      ? `<li><button class="link-btn" data-values="${esc(key)}">fewer</button></li>` : "";
  return `${answers.length ? `<ul class="vm-values">${list.map(item).join("")}${toggle}</ul>` : ""}
    ${missing.length ? `<ul class="vm-values is-na" title="Missing-value codes: become NA in a download with that option on">
      <li class="vm-key">Missing</li>${missing.map(item).join("")}</ul>` : ""}`;
}

/* The same label at other sweeps. Exact wording only (case and spacing
   aside), so it is a shortcut, not a claim that two variables are the same
   measure: a question reworded between sweeps will not be linked. */
export function buildLabelIndex() {
  const index = new Map();
  for (const row of state.vars) {
    const label = normLabel(row[1]);
    if (label.length < 10) continue;
    if (!index.has(label)) index.set(label, []);
    index.get(label).push(row);
  }
  state.labelIndex = index;
}
const normLabel = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").replace(/[\s.:;?]+$/, "").trim();

function alsoHtml(row) {
  const group = state.labelIndex.get(normLabel(row[1]));
  if (!group || group.length < 2 || group.length > ALSO_GROUP_MAX) return "";
  const keys = waveKeys();
  const others = group.filter((r) => r !== row).sort((a, b) => a[3] - b[3] || a[0].localeCompare(b[0]));
  const links = others.slice(0, ALSO_MAX).map((r) =>
    `<button class="vm-also-link" data-jump="${esc(keyOf(r))}" title="${esc(state.manifest.files[r[2]].name)}">
       <span class="v-wave">${esc(keys[r[3]])}</span> ${esc(r[0])}</button>`).join("");
  const rest = others.length - ALSO_MAX;
  return `<div class="vm-also"><span class="vm-key">Same label</span>${links}${
    rest > 0 ? `<span class="vm-dim">+ ${rest} more</span>` : ""}</div>`;
}

function moreHtml(row) {
  const entry = dictEntry(row);
  if (entry === undefined) return `<p class="vm-note">Loading…</p>`;
  const file = state.manifest.files[row[2]];
  const byId = new Map(state.topics.map((t, i) => [t.id, i]));
  const topicsHtml = (entry?.topics || []).filter(([id]) => byId.has(id)).map(([id, c]) => {
    const i = byId.get(id);
    const pct = Math.round(c * 100);
    return `<button class="vm-topic${pct < state.options.minConf ? " is-below" : ""}" data-topic-open="${i}"
        title="${esc(state.domains[state.topics[i].domain].label)} · filter by this topic">
        ${esc(state.topics[i].label)} <span class="vm-pct">${pct}%</span></button>`;
  }).join("");
  const facts = [
    file.description ? `${esc(file.name)} <span class="vm-dim">— ${esc(file.description)}</span>` : esc(file.name),
    file.study ? `SN ${esc(file.study)}` : "",
    entry?.pos ? `position ${esc(entry.pos)}` : "",
    entry?.measurement ? esc(entry.measurement.toLowerCase()) : "",
    entry?.type || "",
  ].filter(Boolean).join(" · ");
  return `
    ${valuesHtml(row, entry)}
    ${topicsHtml ? `<div class="vm-topics"><span class="vm-key">Topics</span>${topicsHtml}</div>` : ""}
    ${alsoHtml(row)}
    ${!file.hasId ? `<p class="vm-note vm-warn">This file has no ${esc(state.manifest.identifier)} column, so it cannot be merged.</p>` : ""}
    <div class="vm-meta"><span>${facts}</span>
      <button class="link-btn" data-file-open="${row[2]}">all in this file</button></div>`;
}

function toggleRow(row) {
  const key = keyOf(row);
  if (state.expanded.has(key)) state.expanded.delete(key); else state.expanded.add(key);
  const li = document.querySelector(`.vrow[data-key="${CSS.escape(key)}"]`);
  const i = state.matches.indexOf(row);
  if (li) li.outerHTML = rowHtml(row, i, state.query.trim(), waveKeys());
  if (state.expanded.has(key)) fillMore(row);
}

/* Go to another variable: find it by its label, which brings the whole
   same-label family into the list together, and open it. */
async function jumpTo(key) {
  const row = state.vars.find((r) => keyOf(r) === key);
  if (!row) return;
  // Its details first, so the row is scrolled to at its full height.
  try { await loadDict(state.manifest.files[row[2]].name); } catch { /* opens as missing */ }
  state.query = row[1]; $("#q").value = row[1];
  state.waveFilter = null; state.fileFilter = null; state.levelFilter = null;
  state.topicSel = [];
  state.expanded = new Set([key]);
  runSearch();
  document.querySelector(`.vrow[data-key="${CSS.escape(key)}"]`)
    ?.scrollIntoView({ block: "nearest" });
}

export function filterToFile(fileIdx) {
  switchView("search");
  state.fileFilter = fileIdx;
  state.waveFilter = null;
  state.levelFilter = null;
  state.query = "";
  $("#q").value = "";
  runSearch();
  $("#filterbar").scrollIntoView({ block: "start" });
}

function clearAll() {
  state.waveFilter = null; state.fileFilter = null; state.levelFilter = null;
  state.topicSel = [];
  state.query = ""; $("#q").value = "";
  runSearch();
}

/* A line under the chart saying what the study is. */
export function renderAbout() {
  const m = state.manifest;
  $("#ov-about").innerHTML = `<strong>${esc(m.fullName)}</strong>${
    m.description ? ` — ${esc(m.description)}` : ""}
    <span class="vm-dim">${m.counts.variables.toLocaleString()} variables in ${m.counts.files} files.</span>`;
}

/* Set by boot.js: persisting options is the basket's job. */
let onOptionsChange = () => {};
export const onOptions = (fn) => { onOptionsChange = fn; };

export function wire() {
  let timer;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = e.target.value; runSearch(); }, 120);
  });

  $("#results").addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    if (add) {
      const row = state.matches.find((r) => r[0] === add.dataset.add &&
        state.manifest.files[r[2]].name === add.dataset.addFile);
      if (row) basket.toggle(rowPayload(row));
      return;
    }
    const vals = e.target.closest("[data-values]");
    if (vals) {
      const key = vals.dataset.values;
      if (state.allValues.has(key)) state.allValues.delete(key); else state.allValues.add(key);
      const row = state.matches.find((r) => keyOf(r) === key);
      const el = document.getElementById(`more-${key}`);
      if (row && el) el.innerHTML = moreHtml(row);
      return;
    }
    const topic = e.target.closest("[data-topic-open]");
    if (topic) { topics.ensure("t", Number(topic.dataset.topicOpen)); runSearch(); return; }
    const jump = e.target.closest("[data-jump]");
    if (jump) { jumpTo(jump.dataset.jump); return; }
    const file = e.target.closest("[data-file-open]");
    if (file) { filterToFile(Number(file.dataset.fileOpen)); return; }
    if (e.target.closest("[data-clear-all]")) { clearAll(); return; }
    const btn = e.target.closest(".vrow-btn");
    if (btn) toggleRow(state.matches[Number(btn.dataset.i)]);
  });

  $("#more").addEventListener("click", (e) => {
    if (!e.target.closest("#show-more")) return;
    state.shown += PAGE;
    renderResults();
  });

  $("#spine-track").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-wave]");
    if (!btn) return;
    const i = Number(btn.dataset.wave);
    state.waveFilter = state.waveFilter === i ? null : i;
    runSearch();
  });

  $("#active-filters").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-clear]");
    if (!btn) return;
    state[`${btn.dataset.clear}Filter`] = null;
    runSearch();
  });
  topics.wire({ rerun: runSearch, saveOptions: () => onOptionsChange() });

  $("#level").addEventListener("change", (e) => {
    state.levelFilter = e.target.value === "" ? null : Number(e.target.value);
    runSearch();
  });
  $("#clear-filters").addEventListener("click", clearAll);
}
