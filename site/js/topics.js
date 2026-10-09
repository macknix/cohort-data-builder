/* Topics: what is selected, how a selection matches, and the topic rows of
   the overview chart, which are the topic filter.

   The rows are a tree: domains, each opening onto its topics, indented. A
   name toggles that domain or topic in the filter; the squares beside it are
   the same topic by sweep, and a square narrows to that topic at that sweep.

   A selection is a list of items, each a whole domain or one topic. A row of
   the index matches an item if it carries that topic (or any topic of that
   domain) at or above the confidence threshold. Several items combine by the
   any/all switch: ANY is the union ("smoking or alcohol"), ALL the
   intersection ("smoking and pregnancy"). */

import { $ } from "./dom.js";
import { esc, state, waveKeys } from "./state.js";

/* ── The selection ───────────────────────────────────────────────────── */

const same = (a, b) => a.kind === b.kind && a.i === b.i;
const domainOf = (item) => (item.kind === "d" ? item.i : state.topics[item.i].domain);
export const isSelected = (kind, i) => state.topicSel.some((s) => same(s, { kind, i }));
export const itemLabel = (s) =>
  s.kind === "d" ? state.domains[s.i].label : state.topics[s.i].label;

/* Toggle one item. A domain and its own topics do not sit side by side:
   choosing a topic narrows its selected domain to that topic, and choosing a
   domain replaces any of its topics. A domain with a topic chosen opens, so
   the choice is never hidden inside a closed branch. */
export function toggle(kind, i) {
  const item = { kind, i };
  if (isSelected(kind, i)) {
    state.topicSel = state.topicSel.filter((s) => !same(s, item));
    return;
  }
  const d = domainOf(item);
  state.topicSel = state.topicSel.filter((s) =>
    kind === "t" ? !(s.kind === "d" && s.i === d) : !(s.kind === "t" && domainOf(s) === d));
  state.topicSel.push(item);
  if (kind === "t") state.gridExpanded.add(d);
}

/* Select without toggling off: for squares and for topics in a variable. */
export function ensure(kind, i) {
  if (!isSelected(kind, i)) toggle(kind, i);
}

/* How many selected items a row matches, given its topics and domains. */
export function matched(ts, ds) {
  let k = 0;
  for (const s of state.topicSel) if (s.kind === "t" ? ts.includes(s.i) : ds.has(s.i)) k++;
  return k;
}

export const passes = (k) => !state.topicSel.length ||
  (state.topicMode === "all" ? k === state.topicSel.length : k > 0);

/* The phrase for the chart's first row. */
export function selectionTitle() {
  const sel = state.topicSel;
  if (!sel.length) return "";
  if (sel.length > 2) return `${sel.length} topics (${state.topicMode})`;
  return sel.map(itemLabel).join(state.topicMode === "all" ? " and " : " or ");
}

/* ── Counting ────────────────────────────────────────────────────────── */

/* Per-sweep counts for every topic and domain. They ignore the sweep filter
   and the topic selection, because these rows are where both are chosen. */
export function newTally() {
  const n = state.manifest.wave.list.length;
  return {
    gridT: state.topics.map(() => new Uint32Array(n)),
    gridD: state.domains.map(() => new Uint32Array(n)),
  };
}

export function countGrid(tally, ts, ds, wave) {
  for (const t of ts) tally.gridT[t][wave]++;
  for (const d of ds) tally.gridD[d][wave]++;
}

/* Chips for the filter bar: one per selected item, and the any/all switch
   once there is something for it to combine. */
export function chips() {
  const out = state.topicSel.map((s) =>
    `<button class="chip chip-topic" data-unselect="${s.kind}:${s.i}" title="Remove this topic">${esc(itemLabel(s))} ✕</button>`);
  if (state.topicSel.length > 1) {
    const mode = state.topicMode;
    out.push(`<span class="match-mode" role="group" aria-label="Combine topics">
      <button data-mode="any" aria-pressed="${mode !== "all"}" title="Variables with any of these topics">any</button>
      <button data-mode="all" aria-pressed="${mode === "all"}" title="Variables with every one of these topics">all</button>
    </span>`);
  }
  return out;
}

/* ── The topic rows ──────────────────────────────────────────────────── */

/* Five steps of one hue. Within a topic, a square is shaded against that
   row's busiest sweep — where in the life course the topic is measured.
   Across topics, against the busiest square anywhere, on a log scale so that
   a topic with dozens of variables is not flattened by one with thousands. */
function level(count, rowMax, allMax) {
  if (!count) return 0;
  const r = state.options.gridShade === "abs"
    ? Math.log1p(count) / Math.log1p(allMax)
    : count / rowMax;
  return Math.max(1, Math.ceil(r * 4));
}

function row(kind, i, counts, allMax, expanded) {
  const label = kind === "d" ? state.domains[i].label : state.topics[i].label;
  const desc = kind === "d" ? state.domains[i].description : state.topics[i].description;
  const on = isSelected(kind, i);
  const partly = kind === "d" && !on &&
    state.topicSel.some((s) => s.kind === "t" && domainOf(s) === i);
  const rowMax = Math.max(1, ...counts);
  const keys = waveKeys();
  const total = counts.reduce((a, b) => a + b, 0);
  const cells = [...counts].map((n, w) => {
    const cur = state.waveFilter === w ? " is-col" : "";
    return `<button class="tg-cell${cur}" data-l="${level(n, rowMax, allMax)}" data-cell="${kind}:${i}:${w}"
        title="${esc(label)} at ${esc(keys[w])}: ${n.toLocaleString()} variable${n === 1 ? "" : "s"}"
        aria-label="${esc(label)} at ${esc(keys[w])}: ${n.toLocaleString()}"></button>`;
  }).join("");
  const chevron = kind === "d"
    ? `<button class="tg-chev" data-expand="${i}" aria-expanded="${expanded}"
         aria-label="${expanded ? "Hide" : "Show"} the topics in ${esc(label)}">${expanded ? "▾" : "▸"}</button>`
    : "";
  return `<div class="ov-row tg-row${kind === "t" ? " is-topic" : ""}${on ? " is-on" : ""}${partly ? " is-part" : ""}">
    <div class="ov-label">${chevron}<button class="tg-name" data-row="${kind}:${i}" aria-pressed="${on}"
        title="${esc(desc || "")}"><span class="tg-box" aria-hidden="true"></span>${kind === "d"
        ? `<span class="dom-swatch" data-domain="${esc(state.domains[i].id)}" aria-hidden="true"></span>` : ""}<span class="tg-text">${esc(label)}</span></button>
      <span class="ov-count">${total ? total.toLocaleString() : "—"}</span></div>
    <div class="tg-cells">${cells}</div></div>`;
}

export function renderGrid() {
  const section = $("#tgrid");
  const has = state.domains.length > 0;
  section.hidden = !has;
  if (!has) return;

  $("#min-conf").value = String(state.options.minConf);
  $("#shade").value = state.options.gridShade;
  const open = state.options.gridOpen;
  // The tag threshold and the shading sit with the topic rows, out of the
  // way until they are opened.
  $("#tg-tools").hidden = !open;
  $("#tgrid-toggle").setAttribute("aria-expanded", String(open));
  $("#tgrid-toggle .tg-caret").textContent = open ? "▾" : "▸";
  const body = $("#tgrid-body");
  body.hidden = !open;
  if (!open) return;

  const { gridT, gridD } = state.tally;
  const allMax = Math.max(1, ...gridD.flatMap((r) => [...r]));
  const parts = [];
  state.domains.forEach((d, di) => {
    const expanded = state.gridExpanded.has(di);
    parts.push(row("d", di, gridD[di], allMax, expanded));
    if (expanded) {
      state.topics.forEach((t, ti) => {
        if (t.domain === di) parts.push(row("t", ti, gridT[ti], allMax, false));
      });
    }
  });
  body.innerHTML = parts.join("");
}

/* ── Wiring ──────────────────────────────────────────────────────────── */

export function wire({ rerun, saveOptions }) {
  $("#min-conf").addEventListener("change", (e) => {
    state.options.minConf = Number(e.target.value);
    saveOptions();
    rerun();
  });
  $("#shade").addEventListener("change", (e) => {
    state.options.gridShade = e.target.value;
    saveOptions();
    renderGrid();
  });

  $("#active-filters").addEventListener("click", (e) => {
    const un = e.target.closest("[data-unselect]");
    if (un) {
      const [kind, i] = un.dataset.unselect.split(":");
      toggle(kind, Number(i));
      rerun();
      return;
    }
    const mode = e.target.closest("[data-mode]");
    if (mode) { state.topicMode = mode.dataset.mode; rerun(); }
  });

  $("#tgrid-toggle").addEventListener("click", () => {
    state.options.gridOpen = !state.options.gridOpen;
    saveOptions();
    renderGrid();
  });

  $("#tgrid-body").addEventListener("click", (e) => {
    const exp = e.target.closest("[data-expand]");
    if (exp) {
      const d = Number(exp.dataset.expand);
      if (state.gridExpanded.has(d)) state.gridExpanded.delete(d); else state.gridExpanded.add(d);
      renderGrid();
      return;
    }
    const name = e.target.closest("[data-row]");
    if (name) {
      const [kind, i] = name.dataset.row.split(":");
      toggle(kind, Number(i));
      rerun();
      return;
    }
    // A square: that topic, at that sweep. The same square again lets go of
    // the sweep and keeps the topic.
    const cell = e.target.closest("[data-cell]");
    if (cell) {
      const [kind, i, w] = cell.dataset.cell.split(":");
      const wave = Number(w);
      const already = isSelected(kind, Number(i)) && state.waveFilter === wave;
      ensure(kind, Number(i));
      state.waveFilter = already ? null : wave;
      rerun();
    }
  });
}
